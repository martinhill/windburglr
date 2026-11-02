import json
from datetime import datetime, UTC, timedelta

import pytest

from tests.sse import open_sse

STATUS_FIELDS = [
    "station_name",
    "status",
    "last_success",
    "last_attempt",
    "error_message",
    "retry_count",
]


def status_update(station="CYTZ", status="error", error_message="Connection timeout", retry_count=3):
    return {
        "station_name": station,
        "status": status,
        "last_success": (datetime.now(UTC) - timedelta(minutes=30)).isoformat(),
        "last_attempt": datetime.now(UTC).isoformat(),
        "error_message": error_message,
        "retry_count": retry_count,
    }


@pytest.mark.asyncio
@pytest.mark.timeout(2)
async def test_scraper_status_initial_connection(start_mock_app, mock_test_db_manager):
    """The scraper status is the first event on a new live stream."""
    mock_test_db_manager.create_test_data("CYTZ")

    async with start_mock_app() as app, open_sse(app, "/api/live/CYTZ") as stream:
        event = await stream.next_event()
        assert event.event == "status"


@pytest.mark.asyncio
@pytest.mark.timeout(2)
async def test_scraper_status_no_wind_data(start_mock_app, mock_test_db_manager):
    """A station without observations gets its status, then only heartbeats."""
    mock_test_db_manager.create_test_stations(
        [{"name": "CYYZ", "timezone": "America/Toronto"}]
    )

    async with (
        start_mock_app(live_heartbeat_interval=0.05) as app,
        open_sse(app, "/api/live/CYYZ") as stream,
    ):
        assert (await stream.next_event()).event == "status"
        assert (await stream.next_event()).event == "heartbeat"


@pytest.mark.asyncio
@pytest.mark.timeout(2)
async def test_scraper_status_update_notification(
    start_mock_app, mock_test_db_manager, mock_listener_connection
):
    """Status changes are pushed to open streams."""
    mock_test_db_manager.create_test_data("CYTZ")

    async with start_mock_app() as app:
        update = status_update()
        await mock_listener_connection.trigger_notification(
            "scraper_status_update", json.dumps(update)
        )

        async with open_sse(app, "/api/live/CYTZ") as stream:
            status = (await stream.next_event()).data
            assert status["station_name"] == "CYTZ"
            assert status["status"] == "error"
            assert status["error_message"] == "Connection timeout"
            assert status["retry_count"] == 3
            assert (await stream.next_event()).event == "wind"

            update = status_update(status="healthy", error_message=None, retry_count=0)
            await mock_listener_connection.trigger_notification(
                "scraper_status_update", json.dumps(update)
            )

            event = await stream.next_event_of("status")
            assert event.data["station_name"] == "CYTZ"
            assert event.data["status"] == "healthy"
            assert event.data["error_message"] is None
            assert event.data["retry_count"] == 0


@pytest.mark.asyncio
@pytest.mark.timeout(2)
async def test_scraper_status_multiple_stations(
    start_mock_app, mock_test_db_manager, mock_listener_connection
):
    """Each station's stream starts with that station's status."""
    mock_test_db_manager.create_test_data("CYTZ")
    mock_test_db_manager.create_test_data("CYYZ")

    async with start_mock_app() as app:
        for station in ("CYTZ", "CYYZ"):
            await mock_listener_connection.trigger_notification(
                "scraper_status_update", json.dumps(status_update(station))
            )

        for station in ("CYTZ", "CYYZ"):
            async with open_sse(app, f"/api/live/{station}") as stream:
                status = await stream.next_event()
                assert status.event == "status"
                assert status.data["station_name"] == station
                assert status.data["status"] == "error"
                assert status.data["retry_count"] == 3
                assert (await stream.next_event()).event == "wind"


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_scraper_status_update_only_reaches_its_station(
    start_mock_app, mock_listener_connection, mock_test_db_manager
):
    """A station's status change goes to that station's streams only."""
    mock_test_db_manager.create_test_data("CYTZ")
    mock_test_db_manager.create_test_data("CYYZ")

    async with (
        start_mock_app() as app,
        open_sse(app, "/api/live/CYTZ") as cytz,
        open_sse(app, "/api/live/CYYZ") as cyyz,
    ):
        await cytz.next_event_of("wind")
        await cyyz.next_event_of("wind")

        update = status_update(status="maintenance", error_message=None, retry_count=0)
        await mock_listener_connection.trigger_notification(
            "scraper_status_update", json.dumps(update)
        )

        event = await cytz.next_event_of("status")
        assert event.data["station_name"] == "CYTZ"
        assert event.data["status"] == "maintenance"
        with pytest.raises(TimeoutError):
            await cyyz.next_event_of("status", timeout=0.2)


@pytest.mark.asyncio
@pytest.mark.timeout(2)
async def test_scraper_status_data_structure(
    start_mock_app, mock_test_db_manager, mock_listener_connection
):
    """Status events carry every ScraperStatus field, with timestamps in ISO format."""
    mock_test_db_manager.create_test_data("CYTZ")

    async with start_mock_app() as app:
        update = status_update(status="healthy", error_message=None, retry_count=0)
        await mock_listener_connection.trigger_notification(
            "scraper_status_update", json.dumps(update)
        )

        async with open_sse(app, "/api/live/CYTZ") as stream:
            event = await stream.next_event()
            assert event.event == "status"
            status = event.data

    for field in STATUS_FIELDS:
        assert field in status, f"Missing field: {field}"
    assert status["station_name"] == "CYTZ"
    assert isinstance(status["status"], str)
    assert isinstance(status["retry_count"], int)
    for field in ["last_success", "last_attempt"]:
        if status[field] is not None:
            datetime.fromisoformat(status[field].replace("Z", "+00:00"))


@pytest.mark.asyncio
@pytest.mark.timeout(2)
async def test_scraper_status_update_with_invalid_data(
    start_mock_app, mock_listener_connection, mock_test_db_manager
):
    """Malformed status notifications are dropped without disturbing open streams."""
    mock_test_db_manager.create_test_data("CYTZ")

    async with (
        start_mock_app(live_heartbeat_interval=0.1) as app,
        open_sse(app, "/api/live/CYTZ") as stream,
    ):
        assert (await stream.next_event()).event == "status"
        assert (await stream.next_event()).event == "wind"

        await mock_listener_connection.trigger_notification(
            "scraper_status_update", "invalid json data"
        )
        await mock_listener_connection.trigger_notification(
            "scraper_status_update", json.dumps({"invalid": "structure"})
        )

        # No status event results, and the stream is still alive
        assert (await stream.next_event()).event == "heartbeat"


@pytest.mark.asyncio
async def test_get_scraper_status_route(test_client, mock_test_db_manager):
    """Test the GET /health/scraper-details route after populating watchdog with status updates."""
    # Get the mock listener connection from the test client
    mock_listener_conn = test_client.mock_listener_connection


    # Create status update data for multiple stations
    status_updates = [
        {
            "station_name": "CYTZ",
            "status": "healthy",
            "last_success": datetime.now(UTC).isoformat(),
            "last_attempt": datetime.now(UTC).isoformat(),
            "error_message": None,
            "retry_count": 0,
        },
        {
            "station_name": "CYYZ",
            "status": "error",
            "last_success": (datetime.now(UTC) - timedelta(minutes=30)).isoformat(),
            "last_attempt": datetime.now(UTC).isoformat(),
            "error_message": "Connection timeout",
            "retry_count": 3,
        },
    ]

    # Trigger status update notifications to populate the watchdog service
    for status_update in status_updates:
        await mock_listener_conn.trigger_notification(
            "scraper_status_update", json.dumps(status_update)
        )

    # Make HTTP request to the scraper status endpoint
    response = test_client.get("/health/scraper-details")

    # Should return 200 OK
    assert response.status_code == 200

    # Response should be a list of scraper status objects
    data = response.json()
    assert isinstance(data, list)

    # Should return status for both stations since we triggered updates for them
    assert len(data) == 2

    # Check structure of each status object
    station_names = {status["station_name"] for status in data}
    assert "CYTZ" in station_names
    assert "CYYZ" in station_names

    for status in data:
        assert isinstance(status, dict)

        # Verify required fields are present
        required_fields = [
            "station_name",
            "status",
            "last_success",
            "last_attempt",
            "error_message",
            "retry_count",
        ]
        for field in required_fields:
            assert field in status, f"Missing field: {field}"

        # Verify data types
        assert isinstance(status["station_name"], str)
        assert isinstance(status["status"], str)
        assert isinstance(status["retry_count"], int)

        # Optional fields can be None or specific types
        if status["last_success"] is not None:
            assert isinstance(status["last_success"], str)
        if status["last_attempt"] is not None:
            assert isinstance(status["last_attempt"], str)
        if status["error_message"] is not None:
            assert isinstance(status["error_message"], str)

        # Check specific status values
        if status["station_name"] == "CYTZ":
            assert status["status"] == "healthy"
            assert status["error_message"] is None
            assert status["retry_count"] == 0
        elif status["station_name"] == "CYYZ":
            assert status["status"] == "error"
            assert status["error_message"] == "Connection timeout"
            assert status["retry_count"] == 3


def test_get_scraper_status_route_no_data(test_client, mock_test_db_manager):
    """Test the GET /health/scraper-details route when no scraper status data exists."""
    # Don't create any test data - test empty state

    # Make HTTP request to the scraper status endpoint
    response = test_client.get("/health/scraper-details")

    # Should return 200 OK even with no data
    assert response.status_code == 200

    # Response should be an empty list
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 0


@pytest.mark.asyncio
async def test_watchdog_no_broadcast_when_no_changes():
    """Test that watchdog does not broadcast updates if the status and retry_count do not change."""
    from app.services.watchdog import WatchdogService
    from app.models import ScraperStatus
    from datetime import datetime, UTC, timedelta
    from unittest.mock import MagicMock

    from app.services.live_updates import status_event

    # Create watchdog service
    watchdog = WatchdogService()

    broadcaster = MagicMock()
    watchdog.set_broadcaster(broadcaster)

    # Create initial status
    initial_status = ScraperStatus(
        station_name="CYTZ",
        status="healthy",
        last_success=datetime.now(UTC) - timedelta(minutes=5),
        last_attempt=datetime.now(UTC) - timedelta(minutes=1),
        error_message=None,
        retry_count=0,
        time_since_last_attempt=timedelta(minutes=1),
        time_since_last_success=timedelta(minutes=5),
    )

    # Set initial status directly in the internal dict
    watchdog.scraper_status["CYTZ"] = initial_status

    # Create update with same status and retry_count (only timestamps changed)
    updated_status = ScraperStatus(
        station_name="CYTZ",
        status="healthy",  # Same status
        last_success=datetime.now(UTC) - timedelta(minutes=2),  # Different timestamp
        last_attempt=datetime.now(UTC),  # Different timestamp
        error_message=None,
        retry_count=0,  # Same retry_count
        time_since_last_attempt=timedelta(seconds=30),
        time_since_last_success=timedelta(minutes=2),
    )

    # Handle the update
    await watchdog.handle_scraper_status_update(updated_status)

    broadcaster.publish.assert_not_called()


@pytest.mark.asyncio
async def test_watchdog_broadcast_when_status_changes():
    """Test that watchdog does broadcast updates if the status only changes."""
    from app.services.watchdog import WatchdogService
    from app.models import ScraperStatus
    from datetime import datetime, UTC, timedelta
    from unittest.mock import MagicMock

    from app.services.live_updates import status_event

    # Create watchdog service
    watchdog = WatchdogService()

    broadcaster = MagicMock()
    watchdog.set_broadcaster(broadcaster)

    # Create initial status
    initial_status = ScraperStatus(
        station_name="CYTZ",
        status="healthy",
        last_success=datetime.now(UTC) - timedelta(minutes=5),
        last_attempt=datetime.now(UTC) - timedelta(minutes=1),
        error_message=None,
        retry_count=0,
        time_since_last_attempt=timedelta(minutes=1),
        time_since_last_success=timedelta(minutes=5),
    )

    # Set initial status directly in the internal dict
    watchdog.scraper_status["CYTZ"] = initial_status

    # Create update with changed status (retry_count same)
    updated_status = ScraperStatus(
        station_name="CYTZ",
        status="error",  # Changed status
        last_success=datetime.now(UTC) - timedelta(minutes=5),
        last_attempt=datetime.now(UTC),
        error_message="Connection timeout",
        retry_count=0,  # Same retry_count
        time_since_last_attempt=timedelta(seconds=30),
        time_since_last_success=timedelta(minutes=5),
    )

    # Handle the update
    await watchdog.handle_scraper_status_update(updated_status)

    broadcaster.publish.assert_called_once_with("CYTZ", status_event(updated_status))


@pytest.mark.asyncio
async def test_watchdog_broadcast_when_retry_count_changes():
    """Test that watchdog does broadcast updates if the retry_count only changes."""
    from app.services.watchdog import WatchdogService
    from app.models import ScraperStatus
    from datetime import datetime, UTC, timedelta
    from unittest.mock import MagicMock

    from app.services.live_updates import status_event

    # Create watchdog service
    watchdog = WatchdogService()

    broadcaster = MagicMock()
    watchdog.set_broadcaster(broadcaster)

    # Create initial status
    initial_status = ScraperStatus(
        station_name="CYTZ",
        status="error",
        last_success=datetime.now(UTC) - timedelta(minutes=30),
        last_attempt=datetime.now(UTC) - timedelta(minutes=1),
        error_message="Connection timeout",
        retry_count=2,
        time_since_last_attempt=timedelta(minutes=1),
        time_since_last_success=timedelta(minutes=30),
    )

    # Set initial status directly in the internal dict
    watchdog.scraper_status["CYTZ"] = initial_status

    # Create update with changed retry_count (status same)
    updated_status = ScraperStatus(
        station_name="CYTZ",
        status="error",  # Same status
        last_success=datetime.now(UTC) - timedelta(minutes=30),
        last_attempt=datetime.now(UTC),
        error_message="Connection timeout",
        retry_count=3,  # Changed retry_count
        time_since_last_attempt=timedelta(seconds=30),
        time_since_last_success=timedelta(minutes=30),
    )

    # Handle the update
    await watchdog.handle_scraper_status_update(updated_status)

    broadcaster.publish.assert_called_once_with("CYTZ", status_event(updated_status))
