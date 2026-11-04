"""Configuration errors are reported to Sentry with the station's config attached."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from unittest.mock import ANY, AsyncMock, MagicMock

import aiohttp
import pytest
import sentry_sdk

from windscraper.config import StationConfig
from windscraper.models import (
    ConfigurationError,
    MaxRetriesExceededError,
    ParserRefreshError,
    WindObs,
)
from windscraper.scraper import (
    RetryHandler,
    Scraper,
    station_config_context,
)


@pytest.fixture
def sentry_events():
    """Initialise Sentry with a hook that collects events instead of sending them."""
    events: list[dict[str, Any]] = []

    def collect(event, hint):
        events.append(event)
        return None

    sentry_sdk.init(dsn="https://public@sentry.invalid/1", before_send=collect)
    yield events
    sentry_sdk.get_client().close()
    # Explicit empty dsn: init() with none would read SENTRY_DSN from the env
    sentry_sdk.init(dsn="")


def make_scraper(
    station_config: StationConfig,
    parser=None,
    parser_factory=None,
    data_requester=None,
    parser_refresh_interval=None,
) -> Scraper:
    tracker = MagicMock()
    tracker.is_new_obs.return_value = True
    return Scraper(
        station_config,
        data_requester or AsyncMock(return_value="{}"),
        parser,
        AsyncMock(),
        AsyncMock(),
        tracker,
        RetryHandler(max_retries=0),
        parser_factory,
        parser_refresh_interval,
    )


def test_station_config_context_is_complete(sample_station_config: StationConfig):
    context = station_config_context(sample_station_config)

    assert context["name"] == "TEST_STATION"
    assert context["url"] == "https://example.com/api/test"
    assert context["headers"] == {"User-Agent": "test-agent"}
    assert context["local_timezone"] == "America/Toronto"
    assert context["timezone"] == "UTC"
    # Unset options are included too
    assert "encryption" in context and context["encryption"] is None


@pytest.mark.asyncio
async def test_configuration_errors_carry_their_own_station_config(
    sample_station_config: StationConfig, sentry_events
):
    """Concurrently processed stations: parse and key failures are reported, each with
    its own config; network failures aren't."""
    parse_fails = replace(sample_station_config, name="PARSE", url="https://parse/")
    key_fails = replace(
        sample_station_config,
        name="KEY",
        key_url="https://key/",
        key_extract_regex='rawKey = "(.+)"',
    )
    network_fails = replace(sample_station_config, name="NET")

    results = await asyncio.gather(
        make_scraper(parse_fails, parser=MagicMock(side_effect=KeyError("speed"))).run_once(),
        make_scraper(
            key_fails,
            parser_factory=AsyncMock(side_effect=ValueError("key_extract_regex no match")),
        ).run_once(),
        make_scraper(
            network_fails,
            parser=MagicMock(),
            data_requester=AsyncMock(side_effect=aiohttp.ClientConnectionError()),
        ).run_once(),
        return_exceptions=True,
    )

    assert isinstance(results[0], ConfigurationError)
    assert isinstance(results[1], ConfigurationError)
    assert isinstance(results[2], MaxRetriesExceededError)

    by_station = {event["tags"]["station"]: event for event in sentry_events}
    assert set(by_station) == {"PARSE", "KEY"}

    parse_event = by_station["PARSE"]
    assert parse_event["level"] == "error"
    assert parse_event["contexts"]["station_config"]["url"] == "https://parse/"
    exception_types = [v["type"] for v in parse_event["exception"]["values"]]
    assert exception_types == ["KeyError", "ConfigurationError"]

    key_event = by_station["KEY"]
    key_context = key_event["contexts"]["station_config"]
    assert key_context["key_url"] == "https://key/"
    assert key_context["key_extract_regex"] == 'rawKey = "(.+)"'


@pytest.mark.asyncio
async def test_parser_recreated_after_parse_failure(
    sample_station_config: StationConfig, sample_wind_obs: WindObs
):
    """A factory-made parser is reused while it works, and made again (fetching the key
    again) after it fails."""
    working = MagicMock(return_value=sample_wind_obs)
    failing = MagicMock(side_effect=ValueError("Padding is incorrect."))
    factory = AsyncMock(return_value=working)
    scraper = make_scraper(sample_station_config, parser_factory=factory)

    await scraper.run_once()
    await scraper.run_once()
    assert factory.await_count == 1

    scraper.parser = failing
    with pytest.raises(ConfigurationError):
        await scraper.run_once()
    await scraper.run_once()
    assert factory.await_count == 2


REFRESH_INTERVAL = 3600.0


async def scraper_due_for_refresh(
    station_config: StationConfig, working, factory: AsyncMock
) -> Scraper:
    """A scraper whose first parser (``working``) was made a refresh interval ago,
    with ``factory`` reset so it only counts refreshes."""
    scraper = make_scraper(
        station_config,
        parser_factory=AsyncMock(return_value=working),
        parser_refresh_interval=REFRESH_INTERVAL,
    )
    await scraper.run_once()
    assert scraper._parser_made_at is not None
    scraper._parser_made_at -= REFRESH_INTERVAL
    scraper.parser_factory = factory
    return scraper


@pytest.mark.asyncio
async def test_parser_not_refreshed_before_interval(
    sample_station_config: StationConfig, sample_wind_obs: WindObs
):
    factory = AsyncMock(return_value=MagicMock(return_value=sample_wind_obs))
    scraper = make_scraper(
        sample_station_config,
        parser_factory=factory,
        parser_refresh_interval=REFRESH_INTERVAL,
    )

    await scraper.run_once()
    await scraper.run_once()

    assert factory.await_count == 1


@pytest.mark.asyncio
async def test_parser_refresh_replaces_working_parser(
    sample_station_config: StationConfig, sample_wind_obs: WindObs, sentry_events
):
    working = MagicMock(return_value=sample_wind_obs)
    fresh = MagicMock(return_value=sample_wind_obs)
    factory = AsyncMock(return_value=fresh)
    scraper = await scraper_due_for_refresh(sample_station_config, working, factory)

    await scraper.run_once()

    assert factory.await_count == 1
    assert scraper.parser is fresh
    assert sentry_events == []
    # Not due again for another interval
    await scraper.run_once()
    assert factory.await_count == 1


@pytest.mark.asyncio
async def test_failed_key_discovery_reported_while_current_parser_kept(
    sample_station_config: StationConfig, sample_wind_obs: WindObs, sentry_events
):
    """The site moved the key: reported as a ParserRefreshError, while the key found
    earlier keeps the station healthy."""
    working = MagicMock(return_value=sample_wind_obs)
    factory = AsyncMock(side_effect=ValueError("key_extract_regex no match"))
    scraper = await scraper_due_for_refresh(sample_station_config, working, factory)

    await scraper.run_once()

    assert scraper.parser is working
    scraper.output_handler.assert_awaited_with(sample_wind_obs)
    scraper.status_handler.assert_awaited_with("TEST_STATION", "healthy", "")
    [event] = sentry_events
    assert event["level"] == "error"
    assert event["tags"]["station"] == "TEST_STATION"
    exception_types = [v["type"] for v in event["exception"]["values"]]
    assert exception_types == ["ValueError", "ParserRefreshError"]
    # Not retried until the next interval
    await scraper.run_once()
    assert factory.await_count == 1


@pytest.mark.asyncio
async def test_new_parser_that_cant_parse_current_data_is_rejected(
    sample_station_config: StationConfig, sample_wind_obs: WindObs, sentry_events
):
    """A key was found, but it's the wrong one."""
    working = MagicMock(return_value=sample_wind_obs)
    wrong_key = MagicMock(side_effect=ValueError("Padding is incorrect."))
    factory = AsyncMock(return_value=wrong_key)
    scraper = await scraper_due_for_refresh(sample_station_config, working, factory)

    await scraper.run_once()

    assert scraper.parser is working
    scraper.output_handler.assert_awaited_with(sample_wind_obs)
    [event] = sentry_events
    assert event["exception"]["values"][-1]["type"] == ParserRefreshError.__name__


@pytest.mark.asyncio
async def test_parser_refresh_network_failure_not_reported(
    sample_station_config: StationConfig, sample_wind_obs: WindObs, sentry_events
):
    working = MagicMock(return_value=sample_wind_obs)
    factory = AsyncMock(side_effect=aiohttp.ClientConnectionError())
    scraper = await scraper_due_for_refresh(sample_station_config, working, factory)

    await scraper.run_once()

    assert scraper.parser is working
    assert sentry_events == []


@pytest.mark.asyncio
async def test_station_outages_not_reported(
    sample_station_config: StationConfig, sample_wind_obs: WindObs, sentry_events
):
    """Stale data and an unreachable station are shown by the webapp, not Sentry."""
    stale = make_scraper(
        sample_station_config, parser=MagicMock(return_value=sample_wind_obs)
    )
    stale.tracker.is_new_obs.return_value = False
    stale.tracker.get_last_obs_time.return_value = datetime(2020, 1, 1, tzinfo=UTC)
    down = make_scraper(
        replace(sample_station_config, name="DOWN"),
        parser=MagicMock(),
        data_requester=AsyncMock(side_effect=aiohttp.ClientConnectionError()),
    )

    results = await asyncio.gather(
        stale.run_once(), down.run_once(), return_exceptions=True
    )

    assert [type(r).__name__ for r in results] == [
        "StaleWindObservationError",
        "MaxRetriesExceededError",
    ]
    stale.status_handler.assert_awaited_with(
        "TEST_STATION", "stale_data", ANY
    )
    assert sentry_events == []
