"""Test the application endpoints.

TODO: Test /day redirect at local day start/end boundaries
"""

import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pydantic import BaseModel, ValidationError, types

from app.models import WindDataPoint

logger = logging.getLogger(__name__)


def is_wind_data_ok(
    wind_data: list[tuple], test_input_data: list[dict], start_time: datetime) -> tuple[bool, str]:
    """Check if the wind data is valid."""
    if not wind_data:
        return False, "No wind data"
    test_data_by_timestamp = {
        int(item["update_time"].replace(tzinfo=UTC).timestamp()): item for item in test_input_data
    }
    prev_ts = start_time.replace(tzinfo=UTC).timestamp()
    data_len = len(wind_data)
    for i, data in enumerate(wind_data):
        if len(data) != 4:
            return False, "Invalid wind data format"
        data_point : WindDataPoint = WindDataPoint(
            timestamp=data[0],
            direction=data[1],
            speed_kts=data[2],
            gust_kts=data[3],
        )
        ts : float = data[0]
        if not isinstance(ts, float):
            return False, f"Invalid timestamp {data_point} at index {i}/{data_len}"
        # Check expected ordering
        if ts < prev_ts:
            return False, f"Timestamps not in ascending order: {data_point} at index {i}/{data_len}"

        if int(ts) not in test_data_by_timestamp:
            return False, f"Timestamp not found in test data: {data_point} at index {i}/{data_len}"

        test_item : dict = test_data_by_timestamp[int(ts)]
        test_item['timestamp'] = test_item['update_time']
        test_point : WindDataPoint = WindDataPoint(**test_item)

        if data_point != test_point:
            return False, f"Data point mismatch: {data_point} != {test_point} at index {i}/{data_len}"

        prev_ts = ts

    return True, "Test passed"


def test_health(test_client):
    """Test health endpoint."""
    response = test_client.get("/health")
    assert response.status_code == 200
    health_data = response.json()
    assert health_data["status"] == "unhealthy"
    assert health_data["database"] == "failed"
    assert health_data["websocket"] == "no_connections"
    assert health_data["postgresql_listener"] == "healthy"


def test_root_endpoint(test_client):
    """Test root endpoint returns HTML."""
    response = test_client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "windburglr" in response.text.lower()


def test_day_redirect(test_client):
    """Test day redirect endpoint."""
    response = test_client.get("/day", follow_redirects=False)
    assert response.status_code == 302
    today_iso = datetime.now(ZoneInfo("America/Toronto")).strftime("%Y-%m-%d")
    assert f"/day/{today_iso}" in response.headers["location"]


def test_historical_day_endpoint(test_client):
    """Test historical day endpoint."""
    today = datetime.now().strftime("%Y-%m-%d")
    response = test_client.get(f"/day/{today}")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_historical_day_invalid_date(test_client):
    """Test historical day endpoint with invalid date."""
    response = test_client.get("/day/invalid-date")
    assert response.status_code == 400


def test_api_wind_no_params(test_client):
    """Test API wind endpoint with no parameters."""
    response = test_client.get("/api/wind")
    assert response.status_code == 200

    data = response.json()
    assert "station" in data
    assert "winddata" in data
    assert "timezone" in data
    assert "start_time" in data
    assert "end_time" in data
    assert data["station"] == "CYTZ"  # Default station
    assert isinstance(data["winddata"], list)
    # Check that timezone is a valid timezone string
    z = ZoneInfo(data["timezone"])
    assert isinstance(z, ZoneInfo)
    # Check that start_time and end_time are valid ISO datetime strings

    class TimeValidator(BaseModel):
        start_time: types.datetime
        end_time: types.datetime

    try:
        TimeValidator(start_time=data["start_time"], end_time=data["end_time"])
    except ValidationError:
        assert False, "start_time and end_time should be valid ISO datetime strings"


def test_api_wind_station_param(test_client):
    """Test API wind endpoint with custom station."""
    response = test_client.get("/api/wind?stn=CYYZ")
    assert response.status_code == 200

    data = response.json()
    assert data["station"] == "CYYZ"
    assert isinstance(data["winddata"], list)
    # Check that timezone is a valid timezone string
    z = ZoneInfo(data["timezone"])
    assert isinstance(z, ZoneInfo)
    # Check that start_time and end_time are valid ISO datetime strings

    class TimeValidator(BaseModel):
        start_time: types.datetime
        end_time: types.datetime

    try:
        TimeValidator(start_time=data["start_time"], end_time=data["end_time"])
    except ValidationError:
        assert False, "start_time and end_time should be valid ISO datetime strings"


def test_api_wind_hours_param(test_client, mock_test_db_manager):
    """Test API wind endpoint with hours parameter."""
    test_data = mock_test_db_manager.create_test_data()
    response = test_client.get("/api/wind?hours=6")
    assert response.status_code == 200

    data = response.json()
    assert data["station"] == "CYTZ"
    # Filtering is done by the DB query, not available in unit tests
    assert len(data["winddata"]) == 6 * 60 - 1

    for obs in data["winddata"]:
        assert isinstance(obs, list)
        assert len(obs) == 4
        assert isinstance(obs[0], (int, float))  # timestamp
        assert isinstance(obs[1], int)  # direction
        assert isinstance(obs[2], (int, float))  # speed
        assert isinstance(obs[3], (int, float))  # gust


def test_api_wind_time_range(test_client):
    """Test API wind endpoint with time range."""
    now = datetime.now(UTC)
    from_time = (now - timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%S")
    to_time = now.strftime("%Y-%m-%dT%H:%M:%S")

    response = test_client.get(f"/api/wind?from_time={from_time}&to_time={to_time}")
    assert response.status_code == 200

    data = response.json()
    assert data["station"] == "CYTZ"

    for obs in data["winddata"]:
        assert isinstance(obs, list)
        assert len(obs) == 4
        assert isinstance(obs[0], (int, float))  # timestamp
        assert isinstance(obs[1], int)  # direction
        assert isinstance(obs[2], (int, float))  # speed
        assert isinstance(obs[3], (int, float))  # gust


def test_api_wind_with_minute_interval_data(test_client, mock_test_db_manager):
    """Test API wind endpoint with 1-minute interval test data."""
    # Generate 1 day of test data at 1-minute intervals
    test_data = mock_test_db_manager.create_test_data(station_name="CYTZ", days=1)

    response = test_client.get("/api/wind")
    assert response.status_code == 200

    data = response.json()
    assert "station" in data
    assert "winddata" in data
    assert data["station"] == "CYTZ"

    # Verify we generated the expected amount of test data (1440 records for 1 day)
    assert len(test_data) == 24 * 60  # 24 hours * 60 minutes = 1,440 records

    # Verify data structure is correct (tuples: [timestamp, direction, speed, gust])
    for obs in data["winddata"]:
        assert isinstance(obs, list)
        assert len(obs) == 4
        assert isinstance(obs[0], (int, float))  # timestamp
        assert isinstance(obs[1], int)  # direction
        assert isinstance(obs[2], (int, float))  # speed
        assert isinstance(obs[3], (int, float))  # gust


def test_api_wind_custom_station_with_data(test_client, mock_test_db_manager):
    """Test API wind endpoint with custom station and generated data."""
    # Generate test data for CYYZ station at 1-minute intervals
    test_data = mock_test_db_manager.create_test_data(station_name="CYYZ", days=1)

    response = test_client.get("/api/wind?stn=CYYZ")
    assert response.status_code == 200

    data = response.json()
    assert data["station"] == "CYYZ"

    # Verify we have test data (1440 records for 1 day at 1-minute intervals)
    assert len(test_data) == 24 * 60

    # Verify structure and data consistency
    for obs in data["winddata"]:
        assert isinstance(obs, list)
        assert len(obs) == 4
        assert isinstance(obs[0], (int, float))  # timestamp
        assert isinstance(obs[1], int)  # direction
        assert isinstance(obs[2], (int, float))  # speed
        assert isinstance(obs[3], (int, float))  # gust


def test_api_wind_hours_param_with_generated_data(test_client, mock_test_db_manager):
    """Test API wind endpoint with hours parameter using 1-minute interval data."""
    # Generate 1 day of test data at 1-minute intervals
    test_data = mock_test_db_manager.create_test_data(station_name="CYTZ", days=1)

    response = test_client.get("/api/wind?hours=6")
    assert response.status_code == 200

    data = response.json()
    assert data["station"] == "CYTZ"

    # Verify we have the expected amount of generated data (1440 records for 1 day)
    wind_data = data["winddata"]
    assert len(wind_data) == 6 * 60 - 1

    # The API should return data within the last 6 hours
    # With 1-minute intervals, expect ~360 records for 6 hours
    for obs in data["winddata"]:
        assert isinstance(obs, list)
        assert len(obs) == 4
        assert isinstance(obs[0], (int, float))  # timestamp
        assert isinstance(obs[1], (int, float))  # direction
        assert isinstance(obs[2], (int, float))  # speed
        assert isinstance(obs[3], (int, float))  # gust


def test_create_wind_observation_not_implemented(test_client):
    """Test POST endpoint returns not implemented."""
    sample_data = {
        "station": "CYTZ",
        "direction": 270,
        "speed_kts": 15,
        "gust_kts": 20,
        "update_time": "2024-01-01T12:00:00",
    }

    response = test_client.post("/api/wind", json=sample_data)
    assert response.status_code == 405


def test_api_wind_data_matches_generated_data(test_client, mock_test_db_manager):
    """Test that API wind data matches the generated test data."""
    # Generate test data for CYTZ station at 1-minute intervals
    test_data = mock_test_db_manager.create_test_data(station_name="CYTZ", days=1)

    # Get the API response
    response = test_client.get("/api/wind")
    assert response.status_code == 200

    data = response.json()
    assert data["station"] == "CYTZ"

    # Verify we have the expected data
    api_wind_data = data["winddata"]

    assert len(api_wind_data) == 24*60-1

    # API wind data is a list of lists [timestamp, direction, speed, gust]
    # Test data is a list of dicts with keys: direction, speed_kts, gust_kts, update_time, station

    # Check that each API data point exists in the test data
    test_data_by_timestamp = {int(item["update_time"].replace(tzinfo=UTC).timestamp()): item for item in test_data}

    for api_item in api_wind_data:
        timestamp = int(api_item[0])
        api_point = WindDataPoint(
            timestamp=api_item[0],
            direction=api_item[1],
            speed_kts=api_item[2],
            gust_kts=api_item[3],
        )

        # Verify this timestamp exists in the test data
        assert timestamp in test_data_by_timestamp, (
            f"API timestamp {timestamp} not found in test data"
        )

        test_item = test_data_by_timestamp[timestamp]
        test_item['timestamp'] = test_item['update_time']
        test_point = WindDataPoint(**test_item)

        assert api_point == test_point, (
            f"Data mismatch for timestamp {timestamp}"
        )

def test_api_wind_custom_station_data_matches(test_client, mock_test_db_manager):
    """Test that API wind data for custom station matches the generated test data."""
    # Generate test data for CYYZ station
    test_data = mock_test_db_manager.create_test_data(station_name="CYYZ", days=1)

    # Get the API response for the same station
    response = test_client.get("/api/wind?stn=CYYZ")
    assert response.status_code == 200

    data = response.json()
    assert data["station"] == "CYYZ"

    # Verify we have the expected data
    api_wind_data = data["winddata"]

    # Check that each API data point exists in the test data
    test_data_by_timestamp = {int(item["update_time"].replace(tzinfo=UTC).timestamp()): item for item in test_data}

    for api_item in api_wind_data:
        timestamp = int(api_item[0])
        api_point = WindDataPoint(
            timestamp=api_item[0],
            direction=api_item[1],
            speed_kts=api_item[2],
            gust_kts=api_item[3],
        )

        # Verify this timestamp exists in the test data
        assert timestamp in test_data_by_timestamp, (
            f"API timestamp {timestamp} not found in test data"
        )

        test_item = test_data_by_timestamp[timestamp]
        test_item['timestamp'] = test_item['update_time']
        test_point = WindDataPoint(**test_item)

        assert api_point == test_point, (
            f"Data mismatch for timestamp {timestamp}"
        )


def test_api_wind_hours_param_data_verification(test_client, mock_test_db_manager):
    """Test that API wind data with hours parameter correctly filters and returns expected data."""
    # Generate test data
    test_data = mock_test_db_manager.create_test_data(station_name="CYTZ", days=1)

    # Request only the last 6 hours of data
    hours = 6
    response = test_client.get(f"/api/wind?hours={hours}")
    assert response.status_code == 200

    data = response.json()
    api_wind_data = data["winddata"]

    assert len(api_wind_data) == 60 * hours - 1

    # Calculate the cutoff time (6 hours ago)
    now = datetime.now(UTC)
    cutoff_time = now - timedelta(hours=hours)

    # Convert API data to a lookup dictionary
    api_data_by_timestamp = {int(item[0]): item for item in api_wind_data}

    test_data_by_timestamp = {int(item["update_time"].replace(tzinfo=UTC).timestamp()): item for item in test_data}

    matching_items = 0
    for api_item in api_wind_data:
        timestamp = int(api_item[0])
        api_point = WindDataPoint(
            timestamp=api_item[0],
            direction=api_item[1],
            speed_kts=api_item[2],
            gust_kts=api_item[3],
        )

        # Verify the item exists in the test data
        if timestamp in test_data_by_timestamp:
            test_item = test_data_by_timestamp[timestamp]
            test_item['timestamp'] = test_item['update_time']
            test_point = WindDataPoint(**test_item)

            assert api_point == test_point, (
                f"Data mismatch for timestamp {timestamp}"
            )
            matching_items += 1

    # Verify we found at least some matching items
    assert matching_items > 0, (
        "No matching data points found in the specified time range"
    )


def test_wind_data_caching_simple(test_client, mock_test_db_manager):
    """Test caching mechanism for wind data."""
    # Generate 1 day of test data at 1-minute intervals
    test_data = mock_test_db_manager.create_test_data(station_name="CYTZ", days=1)

    initial_query_count = 0

    # Fetch wind data without caching
    hours = 6
    start_time = datetime.now(UTC) - timedelta(hours=hours)
    response = test_client.get(f"/api/wind?hours={hours}")
    wind_data = response.json()["winddata"]
    assert response.status_code == 200

    # Verify the database was queried (wind data + timezone)
    query_count = len(mock_test_db_manager.get_recorded_queries(contains="get_wind_data"))
    assert query_count == initial_query_count + 1, (
        f"Database was not queried (count: {query_count})"
    )

    assert len(wind_data) == hours * 60 -1, "Wind data length does not match"
    status, reason = is_wind_data_ok(wind_data, test_data, start_time)
    assert status == True, reason

    # Fetch wind data with caching
    start_time = datetime.now(UTC) - timedelta(hours=hours)
    response = test_client.get(f"/api/wind?hours={hours}")
    wind_data2 = response.json()["winddata"]
    assert response.status_code == 200

    # Verify the database was not queried again for wind data (timezone is cached)
    query_count = len(mock_test_db_manager.get_recorded_queries(contains="get_wind_data"))
    assert query_count == initial_query_count + 1, (
        f"Database was queried for wind data (count: {query_count})"
    )

    assert len(wind_data) == len(wind_data2), "Wind data length does not match"
    assert wind_data == wind_data2, (
        f"Wind data does not match {datetime.fromtimestamp(wind_data[-1][0])} != {datetime.fromtimestamp(wind_data2[-1][0])}"
    )

    # Fetch more wind data without caching
    hours = 12
    start_time = datetime.now(UTC) - timedelta(hours=hours)
    response = test_client.get(f"/api/wind?hours={hours}")
    wind_data = response.json()["winddata"]
    assert response.status_code == 200

    # Verify the database was queried again
    query_count = len(mock_test_db_manager.get_recorded_queries(contains="get_wind_data"))
    assert query_count == initial_query_count + 2, (
        f"Database was not queried again (count: {query_count})"
    )

    assert len(wind_data) == hours * 60 -1, "Wind data length does not match"
    status, reason = is_wind_data_ok(wind_data, test_data, start_time)
    assert status == True, reason

    # Fetch wind data with caching
    hours = 24
    start_time = datetime.now(UTC) - timedelta(hours=hours)
    response = test_client.get(f"/api/wind?hours={hours}")
    wind_data = response.json()["winddata"]
    assert response.status_code == 200

    # Verify the database was not queried again
    query_count = len(mock_test_db_manager.get_recorded_queries(contains="get_wind_data"))
    assert query_count == initial_query_count + 3, "Cache hit"

    assert len(wind_data) == hours * 60 -1, "Wind data length does not match"
    status, reason = is_wind_data_ok(wind_data, test_data, start_time)
    assert status == True, reason

    # Fetch wind data with caching
    hours = 3
    start_time = datetime.now(UTC) - timedelta(hours=hours)
    response = test_client.get(f"/api/wind?hours={hours}")
    wind_data = response.json()["winddata"]
    assert response.status_code == 200

    # Verify the database was not queried again
    query_count = len(mock_test_db_manager.get_recorded_queries(contains="get_wind_data"))
    assert query_count == initial_query_count + 3, "Cache miss"

    assert len(wind_data) == hours * 60 -1, "Wind data length does not match"
    status, reason = is_wind_data_ok(wind_data, test_data, start_time)
    assert status == True, reason

    # Fetch wind data with caching
    hours = 1
    start_time = datetime.now(UTC) - timedelta(hours=hours)
    response = test_client.get(f"/api/wind?hours={hours}")
    wind_data = response.json()["winddata"]
    assert response.status_code == 200

    # Verify the database was not queried again
    query_count = len(mock_test_db_manager.get_recorded_queries(contains="get_wind_data"))
    assert query_count == initial_query_count + 3, "Cache miss"

    assert len(wind_data) == hours * 60 -1, "Wind data length does not match"
    status, reason = is_wind_data_ok(wind_data, test_data, start_time)
    assert status == True, reason

    # Fetch wind data with caching
    hours = 1
    start_time = datetime.now(UTC) - timedelta(hours=hours)
    response = test_client.get(f"/api/wind?hours={hours}")
    wind_data = response.json()["winddata"]
    assert response.status_code == 200

    # Verify the database was not queried again
    query_count = len(mock_test_db_manager.get_recorded_queries(contains="get_wind_data"))
    assert query_count == initial_query_count + 3, "Cache miss"

    assert len(wind_data) == hours * 60 -1, "Wind data length does not match"
    status, reason = is_wind_data_ok(wind_data, test_data, start_time)
    assert status == True, reason


@pytest.mark.asyncio
async def test_wind_data_caching_new_wind_obs(test_client, mock_test_db_manager):
    """Test caching mechanism for wind data."""
    mock_listener_conn = test_client.mock_listener_connection

    # Generate 1 day of test data at 1-minute intervals
    test_data = mock_test_db_manager.create_test_data(station_name="CYTZ", days=1)

    initial_query_count = 0

    # Fetch wind data without caching
    hours = 6
    response = test_client.get(f"/api/wind?hours={hours}")
    assert response.status_code == 200

    # Verify the database was queried
    query_count = len(mock_test_db_manager.get_recorded_queries(contains="get_wind_data"))
    assert query_count == initial_query_count + 1, "Cache hit"

    new_obs_update_time = datetime.now(UTC)

    notification_data = {
        "station_name": "CYTZ",
        "update_time": str(new_obs_update_time.timestamp()),
        "direction": 270,
        "speed_kts": 15,
        "gust_kts": 20,
    }

    # Trigger a notification to test the ConnectionManager._handle_notification method
    # This simulates what would happen when PostgreSQL sends a NOTIFY wind_obs_insert
    await mock_listener_conn.trigger_notification("wind_obs_insert", notification_data)

    # Verify that the notification was processed (notification count should increase)
    # assert manager.notification_count == 1

    # The notification system broadcasts to WebSocket connections, but doesn't update the mock database
    # So we just verify the notification was processed successfully
    hours = 6
    start_time = datetime.now(UTC) - timedelta(hours=hours)
    response = test_client.get(f"/api/wind?hours={hours}")
    assert response.status_code == 200

    # Verify the response contains the new wind observation data as the last element
    wind_data = response.json()["winddata"]
    assert wind_data[-1] == [
        new_obs_update_time.timestamp(),
        notification_data["direction"],
        notification_data["speed_kts"],
        notification_data["gust_kts"],
    ]

    # Verify the database was queried again
    query_count = len(mock_test_db_manager.get_recorded_queries(contains="get_wind_data"))
    assert query_count == initial_query_count + 1, "Cache miss"

    test_data.append({
        "station_name": notification_data['station_name'],
        "update_time": new_obs_update_time,
        "direction": notification_data['direction'],
        "speed_kts": notification_data['speed_kts'],
        "gust_kts": notification_data['gust_kts'],
    })
    assert len(wind_data) == hours * 60, "Wind data length does not match"
    status, reason = is_wind_data_ok(wind_data, test_data, start_time)
    assert status == True, reason


def test_wind_data_caching_different_time_ranges(test_client, mock_test_db_manager):
    """Test caching mechanism with different time ranges."""
    # Generate test data
    test_data = mock_test_db_manager.create_test_data(station_name="CYTZ", days=7)

    initial_query_count = 0

    # First request: 6 hours of data
    hours = 12
    response = test_client.get(f"/api/wind?hours={hours}")
    assert response.status_code == 200

    # Verify the database was queried (wind data + timezone)
    query_count = len(mock_test_db_manager.get_recorded_queries(contains="get_wind_data"))
    assert query_count == initial_query_count + 1, (
        f"Database was not queried for initial request (count: {query_count})"
    )

    # Second request: data from 2 days ago - should not be cached
    two_days_ago = datetime.now(UTC) - timedelta(days=2)
    two_days_ago.replace(hour=0, minute=0, second=0, microsecond=0)
    from_time = two_days_ago.strftime("%Y-%m-%dT%H:%M:%S")
    to_time = (two_days_ago + timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S")

    response = test_client.get(f"/api/wind?from_time={from_time}&to_time={to_time}")
    assert response.status_code == 200

    # Verify the database was queried again for different time range
    query_count = len(mock_test_db_manager.get_recorded_queries(contains="get_wind_data"))
    assert query_count == initial_query_count + 2, (
        f"Database was not queried for 2 days ago request (count: {query_count})"
    )

    # Third request: repeat the 6 hours request (should hit cache)
    response = test_client.get(f"/api/wind?hours={hours}")
    assert response.status_code == 200

    # Verify the database was NOT queried again (cache hit)
    query_count = len(mock_test_db_manager.get_recorded_queries(contains="get_wind_data"))
    assert query_count == initial_query_count + 2, (
        f"Database was queried when it should have hit cache (count: {query_count})"
    )
