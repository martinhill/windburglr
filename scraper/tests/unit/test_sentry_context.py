"""Configuration errors are reported to Sentry with the station's config attached."""

import asyncio
from dataclasses import replace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest
import sentry_sdk

from windscraper.config import StationConfig
from windscraper.models import ConfigurationError, MaxRetriesExceededError, WindObs
from windscraper.scraper import RetryHandler, Scraper, station_config_context


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
    sentry_sdk.init()


def make_scraper(
    station_config: StationConfig,
    parser=None,
    parser_factory=None,
    data_requester=None,
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
