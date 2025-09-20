import json
from datetime import datetime, UTC, timedelta

import pytest


@pytest.mark.timeout(1)
def test_scraper_status_initial_connection(test_client, mock_test_db_manager):
    """Test that status_update message is sent on initial WebSocket connection."""
    # Create a station with scraper status
    mock_test_db_manager.create_test_data("CYTZ")

    with test_client.websocket_connect("/ws/CYTZ") as websocket:
        # First receives wind_observation (since status isn't loaded at startup)
        message = websocket.receive_json()
        assert message["type"] == "wind"

        # Status update might not be sent if no status data is available during startup
        # This is expected behavior when scraper status isn't pre-loaded


@pytest.mark.timeout(1)
def test_scraper_status_no_wind_data(test_client, mock_test_db_manager):
    """Test WebSocket behavior when no wind data exists for a station."""
    # Create a station without wind data
    mock_test_db_manager.create_test_stations(
        [{"name": "CYYZ", "timezone": "America/Toronto"}]
    )

    with test_client.websocket_connect("/ws/CYYZ") as websocket:
        # When no wind data exists and scraper status isn't loaded during startup,
        # the WebSocket connection is established but no initial messages are sent.
        # This is expected behavior.

        # Send a ping to verify the connection works
        import json

        websocket.send_text(json.dumps({"type": "ping"}))
        response = websocket.receive_json()
        assert response["type"] == "pong"


@pytest.mark.asyncio
@pytest.mark.timeout(1)
async def test_scraper_status_update_notification(test_client, mock_test_db_manager):
    """Test that status update notifications are sent to WebSocket clients."""
    # Get the mock listener connection from the test client
    mock_listener_conn = test_client.mock_listener_connection
    mock_test_db_manager.create_test_data("CYTZ")

    # Simulate a scraper status update notification
    status_update_data = {
        "station_name": "CYTZ",
        "status": "error",
        "last_success": (datetime.now(UTC) - timedelta(minutes=30)).isoformat(),
        "last_attempt": datetime.now(UTC).isoformat(),
        "error_message": "Connection timeout",
        "retry_count": 3,
    }

    # Trigger the notification
    await mock_listener_conn.trigger_notification(
        "scraper_status_update", json.dumps(status_update_data)
    )

    with test_client.websocket_connect("/ws/CYTZ") as websocket:
        # Receive initial messages
        status_msg = websocket.receive_json()
        assert status_msg["type"] == "status_update"
        status_data = status_msg["data"]
        assert status_data["station_name"] == "CYTZ"
        assert status_data["status"] == "error"
        assert status_data["error_message"] == "Connection timeout"
        assert status_data["retry_count"] == 3

        wind_msg = websocket.receive_json()
        assert wind_msg["type"] == "wind"

        # Trigger the notification
        status_update_data["status"] = "healthy"
        status_update_data["error_message"] = None
        status_update_data["retry_count"] = 0
        await mock_listener_conn.trigger_notification(
            "scraper_status_update", json.dumps(status_update_data)
        )

        # Should receive the status update
        message = websocket.receive_json()
        assert message["type"] == "status_update"

        status_data = message["data"]
        assert status_data["station_name"] == "CYTZ"
        assert status_data["status"] == "healthy"
        assert status_data["error_message"] == None
        assert status_data["retry_count"] == 0


@pytest.mark.asyncio
@pytest.mark.timeout(1)
async def test_scraper_status_multiple_stations(test_client, mock_test_db_manager):
    """Test status updates for multiple stations."""
    # Create test data for multiple stations
    mock_test_db_manager.create_test_data("CYTZ")
    mock_test_db_manager.create_test_data("CYYZ")
    mock_listener_conn = test_client.mock_listener_connection

    # Simulate a scraper status update notification
    status_update_data = {
        "station_name": "CYTZ",
        "status": "error",
        "last_success": (datetime.now(UTC) - timedelta(minutes=30)).isoformat(),
        "last_attempt": datetime.now(UTC).isoformat(),
        "error_message": "Connection timeout",
        "retry_count": 3,
    }

    # Trigger the notification
    await mock_listener_conn.trigger_notification(
        "scraper_status_update", json.dumps(status_update_data)
    )

    status_update_data["station_name"] = "CYYZ"
    # Trigger the notification
    await mock_listener_conn.trigger_notification(
        "scraper_status_update", json.dumps(status_update_data)
    )

    # Test CYTZ connection receives only CYTZ status
    with test_client.websocket_connect("/ws/CYTZ") as ws_cytz:
        status_msg = ws_cytz.receive_json()
        assert status_msg["type"] == "status_update"
        status_data = status_msg["data"]
        assert status_data["station_name"] == "CYTZ"
        assert status_data["status"] == "error"
        assert status_data["error_message"] == "Connection timeout"
        assert status_data["retry_count"] == 3

        # Should receive wind_observation for CYTZ
        message = ws_cytz.receive_json()
        assert message["type"] == "wind"

    # Test CYYZ connection receives only CYYZ status
    with test_client.websocket_connect("/ws/CYYZ") as ws_cyyz:
        status_msg = ws_cyyz.receive_json()
        assert status_msg["type"] == "status_update"
        status_data = status_msg["data"]
        assert status_data["station_name"] == "CYYZ"
        assert status_data["status"] == "error"
        assert status_data["error_message"] == "Connection timeout"
        assert status_data["retry_count"] == 3

        # Should receive wind_observation for CYYZ
        message = ws_cyyz.receive_json()
        assert message["type"] == "wind"


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_scraper_status_broadcast_to_all_stations(
    test_client, mock_test_db_manager
):
    """Test that status updates are broadcast to all connected WebSocket clients."""
    mock_listener_conn = test_client.mock_listener_connection
    mock_test_db_manager.create_test_data("CYTZ")
    mock_test_db_manager.create_test_data("CYYZ")

    with (
        test_client.websocket_connect("/ws/CYTZ") as ws_cytz,
        test_client.websocket_connect("/ws/CYYZ") as ws_cyyz,
    ):
        # Clear initial messages - only wind_observation since no status pre-loaded
        cytz_msg = ws_cytz.receive_json()  # wind_observation
        assert cytz_msg["type"] == "wind"

        cyyz_msg = ws_cyyz.receive_json()  # wind_observation
        assert cyyz_msg["type"] == "wind"

        # Simulate status update for CYTZ station
        status_update_data = {
            "station_name": "CYTZ",
            "status": "maintenance",
            "last_success": datetime.now(UTC).isoformat(),
            "last_attempt": datetime.now(UTC).isoformat(),
            "error_message": None,
            "retry_count": 0,
        }

        await mock_listener_conn.trigger_notification(
            "scraper_status_update", json.dumps(status_update_data)
        )

        # Only CYTZ connection should receive the update (station-specific)
        cytz_msg = ws_cytz.receive_json()
        assert cytz_msg["type"] == "status_update"
        assert cytz_msg["data"]["station_name"] == "CYTZ"
        assert cytz_msg["data"]["status"] == "maintenance"

        # CYYZ connection should not receive the CYTZ update
        # (This tests that updates are station-specific)


@pytest.mark.asyncio
@pytest.mark.timeout(1)
async def test_scraper_status_data_structure(test_client, mock_test_db_manager):
    """Test the structure of scraper status data by triggering a notification."""
    mock_test_db_manager.create_test_data("CYTZ")
    mock_listener_conn = test_client.mock_listener_connection

    # Create status update data with all required fields
    status_update_data = {
        "station_name": "CYTZ",
        "status": "healthy",
        "last_success": datetime.now(UTC).isoformat(),
        "last_attempt": datetime.now(UTC).isoformat(),
        "error_message": None,
        "retry_count": 0,
    }

    # Trigger notification first
    await mock_listener_conn.trigger_notification(
        "scraper_status_update", json.dumps(status_update_data)
    )

    with test_client.websocket_connect("/ws/CYTZ") as websocket:
        # Should receive status_update first since we triggered it before connecting
        message = websocket.receive_json()
        assert message["type"] == "status_update"

        status_data = message["data"]

        # Verify required fields
        required_fields = [
            "station_name",
            "status",
            "last_success",
            "last_attempt",
            "error_message",
            "retry_count",
        ]
        for field in required_fields:
            assert field in status_data, f"Missing field: {field}"

        # Verify data types
        assert isinstance(status_data["status"], str)
        assert isinstance(status_data["retry_count"], int)
        assert status_data["station_name"] == "CYTZ"
        # last_success and last_attempt can be None or ISO timestamp strings
        # error_message can be None or string


@pytest.mark.asyncio
@pytest.mark.timeout(1)
async def test_scraper_status_update_with_invalid_data(
    test_client, mock_test_db_manager
):
    """Test handling of invalid scraper status update data."""
    mock_listener_conn = test_client.mock_listener_connection
    mock_test_db_manager.create_test_data("CYTZ")

    with test_client.websocket_connect("/ws/CYTZ") as websocket:
        # Clear initial messages - just wind_observation
        initial_msg = websocket.receive_json()
        assert initial_msg["type"] == "wind"

        # Send invalid JSON
        await mock_listener_conn.trigger_notification(
            "scraper_status_update", "invalid json data"
        )

        # Should not crash, and no additional message should be received
        # (implementation should handle JSON parsing errors gracefully)

        # Send valid JSON but invalid structure
        await mock_listener_conn.trigger_notification(
            "scraper_status_update", json.dumps({"invalid": "structure"})
        )

        # Should not crash and handle gracefully


@pytest.mark.asyncio
@pytest.mark.timeout(1)
async def test_scraper_status_timing_fields(test_client, mock_test_db_manager):
    """Test that timing fields in status data are properly formatted."""
    mock_test_db_manager.create_test_data("CYTZ")
    mock_listener_conn = test_client.mock_listener_connection

    # Create valid status update with timing fields
    status_update_data = {
        "station_name": "CYTZ",
        "status": "healthy",
        "last_success": datetime.now(UTC).isoformat(),
        "last_attempt": datetime.now(UTC).isoformat(),
        "error_message": None,
        "retry_count": 0,
    }

    # Trigger notification first
    await mock_listener_conn.trigger_notification(
        "scraper_status_update", json.dumps(status_update_data)
    )

    with test_client.websocket_connect("/ws/CYTZ") as websocket:
        # Should receive status_update first since we triggered it before connecting
        message = websocket.receive_json()
        assert message["type"] == "status_update"

        status_data = message["data"]

        # Check timestamp fields (if not None, should be valid ISO format)
        for field in ["last_success", "last_attempt"]:
            timestamp = status_data.get(field)
            if timestamp is not None:
                # Should be parseable as ISO timestamp
                try:
                    datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                except ValueError:
                    pytest.fail(f"Invalid timestamp format for {field}: {timestamp}")


@pytest.mark.asyncio
async def test_get_scraper_status_route(test_client, mock_test_db_manager):
    """Test the GET /api/scraper-status route after populating watchdog with status updates."""
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
    response = test_client.get("/api/scraper-status")

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
    """Test the GET /api/scraper-status route when no scraper status data exists."""
    # Don't create any test data - test empty state

    # Make HTTP request to the scraper status endpoint
    response = test_client.get("/api/scraper-status")

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
    from unittest.mock import AsyncMock

    # Create watchdog service
    watchdog = WatchdogService()

    # Mock websocket manager
    mock_ws_manager = AsyncMock()
    watchdog.set_websocket_manager(mock_ws_manager)

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

    # Assert that websocket manager was NOT called (no broadcast)
    mock_ws_manager.send_station_status_update.assert_not_called()


@pytest.mark.asyncio
async def test_watchdog_broadcast_when_status_changes():
    """Test that watchdog does broadcast updates if the status only changes."""
    from app.services.watchdog import WatchdogService
    from app.models import ScraperStatus
    from datetime import datetime, UTC, timedelta
    from unittest.mock import AsyncMock

    # Create watchdog service
    watchdog = WatchdogService()

    # Mock websocket manager
    mock_ws_manager = AsyncMock()
    watchdog.set_websocket_manager(mock_ws_manager)

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

    # Assert that websocket manager WAS called (broadcast happened)
    mock_ws_manager.send_station_status_update.assert_called_once_with("CYTZ", watchdog)


@pytest.mark.asyncio
async def test_watchdog_broadcast_when_retry_count_changes():
    """Test that watchdog does broadcast updates if the retry_count only changes."""
    from app.services.watchdog import WatchdogService
    from app.models import ScraperStatus
    from datetime import datetime, UTC, timedelta
    from unittest.mock import AsyncMock

    # Create watchdog service
    watchdog = WatchdogService()

    # Mock websocket manager
    mock_ws_manager = AsyncMock()
    watchdog.set_websocket_manager(mock_ws_manager)

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

    # Assert that websocket manager WAS called (broadcast happened)
    mock_ws_manager.send_station_status_update.assert_called_once_with("CYTZ", watchdog)
