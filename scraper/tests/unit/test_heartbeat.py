"""The scraper checks in to one Sentry Cron monitor after each cycle."""

from unittest.mock import patch

import pytest

from windscraper.config import Config
from windscraper.main import StdoutHandler, async_main
from windscraper.scraper import HEARTBEAT_MONITOR_SLUG, Heartbeat


class StopLoop(Exception):
    pass


def test_heartbeat_checks_in_to_the_scraper_monitor():
    with patch("windscraper.scraper.capture_checkin") as capture_checkin:
        Heartbeat().beat()

    capture_checkin.assert_called_once()
    kwargs = capture_checkin.call_args.kwargs
    assert kwargs["monitor_slug"] == HEARTBEAT_MONITOR_SLUG
    assert kwargs["status"] == "ok"
    assert kwargs["monitor_config"]["schedule"] == {
        "type": "interval",
        "value": 5,
        "unit": "minute",
    }
    assert kwargs["monitor_config"]["checkin_margin"] == 5


def test_heartbeat_checks_in_at_most_once_per_min_interval():
    heartbeat = Heartbeat(min_interval=60.0)

    with (
        patch("windscraper.scraper.capture_checkin") as capture_checkin,
        patch("windscraper.scraper.time.monotonic", side_effect=[100.0, 130.0, 161.0]),
    ):
        heartbeat.beat()
        heartbeat.beat()
        heartbeat.beat()

    assert capture_checkin.call_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
async def test_main_loop_beats_after_each_cycle_when_enabled(enabled: bool):
    """With no stations (as if every station were failing, which run_once logs and
    absorbs), the loop still checks in: the monitor tracks the scraper, not the data."""
    config = Config(
        stations=[], refresh_rate=0, output_mode="stdout", heartbeat_monitor=enabled
    )
    cycles = 0

    async def count_cycles(_delay: float) -> None:
        nonlocal cycles
        cycles += 1
        if cycles > 2:
            raise StopLoop

    with (
        patch.object(Heartbeat, "beat") as beat,
        patch("windscraper.main.asyncio.sleep", side_effect=count_cycles),
        pytest.raises(StopLoop),
    ):
        await async_main(config, StdoutHandler)

    assert beat.call_count == (2 if enabled else 0)
