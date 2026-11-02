"""The live-update stream (/api/live/{station}) and its broadcaster."""

import asyncio
import signal
import time
from datetime import UTC, datetime

import pytest

from app.services.live_updates import (
    LiveUpdateBroadcaster,
    status_event,
    wind_event,
)
from app.utils.shutdown import on_shutdown_signal
from tests.sse import open_sse

pytestmark = [pytest.mark.asyncio, pytest.mark.timeout(5)]


def wind_notification(timestamp: float, station: str = "CYTZ") -> dict:
    return {
        "station_name": station,
        "update_time": timestamp,
        "direction": 270,
        "speed_kts": 15,
        "gust_kts": None,
    }


def assert_wind_point(data: dict) -> None:
    assert isinstance(data["timestamp"], float)
    assert data["direction"] is None or 0 <= data["direction"] <= 360
    assert isinstance(data["speed_kts"], int)


async def test_fresh_stream_sends_status_then_latest(start_mock_app, mock_test_db_manager):
    mock_test_db_manager.create_test_data("CYTZ")
    async with start_mock_app() as app, open_sse(app, "/api/live/CYTZ") as stream:
        assert stream.status_code == 200
        assert stream.headers["content-type"].startswith("text/event-stream")
        assert stream.headers["cache-control"] == "no-cache"

        status = await stream.next_event()
        assert status.event == "status"
        assert status.data["station_name"] == "CYTZ"

        latest = await stream.next_event()
        assert latest.event == "wind"
        assert_wind_point(latest.data)
        assert latest.id == str(latest.data["timestamp"])
        assert stream.retry == 3000


async def test_streams_are_per_station(start_mock_app, mock_test_db_manager, mock_listener_connection):
    mock_test_db_manager.create_test_data("CYTZ")
    mock_test_db_manager.create_test_data("CYYZ")
    async with (
        start_mock_app() as app,
        open_sse(app, "/api/live/CYTZ") as cytz,
        open_sse(app, "/api/live/CYYZ") as cyyz,
    ):
        await cytz.next_event_of("wind")
        await cyyz.next_event_of("wind")
        assert app.state.live_broadcaster.connection_count == 2

        now = time.time()
        await mock_listener_connection.trigger_notification(
            "wind_obs_insert", wind_notification(now, "CYYZ")
        )
        event = await cyyz.next_event_of("wind")
        assert event.data["timestamp"] == now
        with pytest.raises(TimeoutError):
            await cytz.next_event_of("wind", timeout=0.2)


async def test_new_observation_is_pushed(start_mock_app, mock_test_db_manager, mock_listener_connection):
    mock_test_db_manager.create_test_data("CYTZ")
    async with start_mock_app() as app, open_sse(app, "/api/live/CYTZ") as stream:
        await stream.next_event_of("wind")

        new_time = datetime.now().timestamp()
        await mock_listener_connection.trigger_notification(
            "wind_obs_insert", wind_notification(new_time)
        )

        event = await stream.next_event_of("wind")
        assert event.id == str(new_time)
        assert event.data == {
            "timestamp": new_time,
            "direction": 270,
            "speed_kts": 15,
            "gust_kts": None,
        }


@pytest.mark.parametrize("since_header", [False, True])
async def test_resume_replays_missed_observations(start_mock_app, mock_test_db_manager, since_header):
    """A client resuming with `since` or Last-Event-ID first gets what it missed."""
    mock_test_db_manager.create_test_data("CYTZ")
    since = time.time() - 30 * 60
    if since_header:
        # The browser's Last-Event-ID wins over the `since` the stream was opened with
        url, headers = "/api/live/CYTZ?since=0", {"Last-Event-ID": str(since)}
    else:
        url, headers = f"/api/live/CYTZ?since={since}", None

    async with start_mock_app() as app, open_sse(app, url, headers) as stream:
        backfill = await stream.next_event_of("backfill")
        points = backfill.data
        assert 28 <= len(points) <= 31  # one a minute
        assert all(point[0] > since for point in points)
        assert points == sorted(points)
        assert backfill.id == str(points[-1][0])
        # The replay ends with the latest, so it isn't sent again
        with pytest.raises(TimeoutError):
            await stream.next_event_of("wind", timeout=0.2)


async def test_resume_replay_is_capped_at_24_hours(start_mock_app, mock_test_db_manager):
    mock_test_db_manager.create_test_data("CYTZ", days=2)
    since = time.time() - 40 * 3600
    async with start_mock_app() as app, open_sse(app, f"/api/live/CYTZ?since={since}") as stream:
        points = (await stream.next_event_of("backfill")).data
        assert points[0][0] >= time.time() - 24 * 3600 - 60
        assert 24 * 60 - 2 <= len(points) <= 24 * 60 + 1


@pytest.mark.parametrize("last_event_id", ["garbage", "nan", "inf"])
async def test_unusable_resume_point_sends_latest(start_mock_app, mock_test_db_manager, last_event_id):
    mock_test_db_manager.create_test_data("CYTZ")
    async with (
        start_mock_app() as app,
        open_sse(app, "/api/live/CYTZ", {"Last-Event-ID": last_event_id}) as stream,
    ):
        assert (await stream.next_event_of("wind", "backfill")).event == "wind"


async def test_up_to_date_client_gets_latest_for_current_conditions(start_mock_app, mock_test_db_manager):
    mock_test_db_manager.create_test_data("CYTZ")
    async with start_mock_app() as app, open_sse(app, f"/api/live/CYTZ?since={time.time()}") as stream:
        assert (await stream.next_event_of("wind", "backfill")).event == "wind"


async def test_observations_published_during_replay_are_not_repeated(start_mock_app, mock_test_db_manager):
    mock_test_db_manager.create_test_data("CYTZ")
    since = time.time() - 10 * 60
    async with start_mock_app() as app, open_sse(app, f"/api/live/CYTZ?since={since}") as stream:
        points = (await stream.next_event_of("backfill")).data
        broadcaster = app.state.live_broadcaster
        last = points[-1]
        point = {"timestamp": last[0], "direction": last[1], "speed_kts": last[2], "gust_kts": last[3]}
        broadcaster.publish("CYTZ", wind_event(point))
        newer = dict(point, timestamp=last[0] + 60)
        broadcaster.publish("CYTZ", wind_event(newer))

        event = await stream.next_event_of("wind")
        assert event.data["timestamp"] == newer["timestamp"]


@pytest.mark.parametrize("live_heartbeat_interval", [0.05])
async def test_idle_stream_sends_heartbeats(start_mock_app, live_heartbeat_interval):
    """Heartbeats are real events, so the browser can see the stream is alive."""
    async with (
        start_mock_app(live_heartbeat_interval=live_heartbeat_interval) as app,
        open_sse(app, "/api/live/CYTZ") as stream,
    ):
        assert (await stream.next_event_of("heartbeat")).data == {}
        assert (await stream.next_event_of("heartbeat")).data == {}


async def test_status_change_is_pushed(start_mock_app, mock_test_db_manager, mock_listener_connection):
    mock_test_db_manager.create_test_data("CYTZ")
    async with start_mock_app() as app, open_sse(app, "/api/live/CYTZ") as stream:
        await stream.next_event_of("wind")
        await mock_listener_connection.trigger_notification(
            "scraper_status_update",
            {
                "station_name": "CYTZ",
                "status": "error",
                "last_success": datetime.now(UTC).isoformat(),
                "last_attempt": datetime.now(UTC).isoformat(),
                "error_message": "Timeout",
                "retry_count": 3,
            },
        )
        event = await stream.next_event_of("status")
        assert event.data["status"] == "error"
        assert event.data["retry_count"] == 3


async def test_disconnect_unsubscribes(start_mock_app, mock_test_db_manager):
    mock_test_db_manager.create_test_data("CYTZ")
    async with start_mock_app() as app:
        broadcaster = app.state.live_broadcaster
        async with open_sse(app, "/api/live/CYTZ") as stream:
            await stream.next_event_of("wind")
            assert broadcaster.connection_count == 1
        assert broadcaster.connection_count == 0


async def test_close_all_ends_open_streams_and_refuses_new_ones(start_mock_app):
    async with start_mock_app() as app:
        broadcaster = app.state.live_broadcaster
        async with open_sse(app, "/api/live/CYTZ") as stream:
            await asyncio.sleep(0.05)
            broadcaster.close_all()
            await stream.wait_for_end()
        async with open_sse(app, "/api/live/CYTZ") as stream:
            await stream.wait_for_end()
        assert broadcaster.connection_count == 0


async def test_shutdown_signal_ends_streams_then_reaches_previous_handler(start_mock_app):
    """The server only shuts the app down once open responses end; a SIGTERM ends
    the live streams, then reaches the handler installed before (the server's)."""
    received: list[int] = []
    original = signal.signal(signal.SIGTERM, lambda sig, frame: received.append(sig))
    try:
        async with start_mock_app() as app:
            async with open_sse(app, "/api/live/CYTZ") as stream:
                await asyncio.sleep(0.05)
                signal.raise_signal(signal.SIGTERM)
                await stream.wait_for_end()
            assert received == [signal.SIGTERM]
        # The previous handler is back once the app has shut down
        signal.raise_signal(signal.SIGTERM)
        assert received == [signal.SIGTERM, signal.SIGTERM]
    finally:
        signal.signal(signal.SIGTERM, original)


async def test_on_shutdown_signal_restores_handler():
    def previous(sig, frame):
        pass

    original = signal.signal(signal.SIGINT, previous)
    try:
        with on_shutdown_signal(lambda: None):
            assert signal.getsignal(signal.SIGINT) is not previous
        assert signal.getsignal(signal.SIGINT) is previous
    finally:
        signal.signal(signal.SIGINT, original)


async def test_slow_stream_is_closed_instead_of_blocking_publishers():
    broadcaster = LiveUpdateBroadcaster(max_queued=2)
    slow = broadcaster.subscribe("CYTZ")
    point = {"timestamp": 1.0, "direction": 1, "speed_kts": 1, "gust_kts": 1}
    for i in range(3):
        broadcaster.publish("CYTZ", wind_event(dict(point, timestamp=float(i))))

    assert slow.closed
    assert broadcaster.connection_count == 0
    received = [event async for event in slow.events(heartbeat_interval=1)]
    assert received == []


async def test_status_event_shape(mock_test_db_manager):
    from app.models import ScraperStatus

    event = status_event(
        ScraperStatus(
            station_name="CYTZ",
            status="healthy",
            last_success=None,
            last_attempt=None,
            error_message=None,
            retry_count=0,
            time_since_last_attempt=None,
            time_since_last_success=None,
        )
    )
    assert event.event == "status"
    assert event.id is None
    assert event.data["station_name"] == "CYTZ"
