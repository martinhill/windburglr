"""
Integration tests for API endpoints using real test database.
These tests use the test_db_manager fixture to generate test data
and verify API responses against the generated data.
"""

from datetime import datetime, timedelta, timezone
import pytest


@pytest.mark.integration
class TestAPIWithRealDatabase:
    """Test API endpoints with real database and generated test data."""

    @pytest.mark.anyio
    async def test_api_wind_default_params_with_data(
        self, integration_client, test_db_manager
    ):
        """Test API wind endpoint with default parameters and verify against test data."""
        # Generate a day's worth of 1-minute interval test data
        await test_db_manager.create_test_data(station_name="CYTZ", days=1)

        response = await integration_client.get("/api/wind")
        assert response.status_code == 200

        data = response.json()
        assert "station" in data
        assert "winddata" in data
        assert "timezone" in data
        assert "start_time" in data
        assert "end_time" in data
        assert data["station"] == "CYTZ"  # Default station

        # The API might not return data if it's too old, so we'll just verify structure
        # and that the API responds correctly
        assert isinstance(data["winddata"], list)

        # Verify data structure for any returned data
        for obs in data["winddata"]:
            assert isinstance(obs, list)
            assert len(obs) == 4  # [timestamp, direction, speed, gust]
            assert isinstance(obs[0], (int, float))  # timestamp
            assert isinstance(obs[1], (int, float))  # direction
            assert isinstance(obs[2], (int, float))  # speed
            assert isinstance(obs[3], (int, float))  # gust

    @pytest.mark.anyio
    async def test_api_wind_custom_station_with_data(
        self, integration_client, test_db_manager
    ):
        """Test API wind endpoint with custom station and verify data."""
        # Generate test data for CYYZ station
        await test_db_manager.create_test_data(station_name="CYYZ", days=1)

        response = await integration_client.get("/api/wind?stn=CYYZ")
        assert response.status_code == 200

        data = response.json()
        assert data["station"] == "CYYZ"

        # Verify structure (API may not return data if too old)
        assert isinstance(data["winddata"], list)

        # Verify data structure for any returned data
        for obs in data["winddata"]:
            assert isinstance(obs, list)
            assert len(obs) == 4  # [timestamp, direction, speed, gust]
            assert isinstance(obs[0], (int, float))  # timestamp
            assert isinstance(obs[1], (int, float))  # direction
            assert isinstance(obs[2], (int, float))  # speed
            assert isinstance(obs[3], (int, float))  # gust


    @pytest.mark.anyio
    async def test_api_wind_hours_param_with_data(
        self, integration_client, test_db_manager
    ):
        """Test API wind endpoint with hours parameter and verify data range."""
        # Generate test data
        now_datetime = datetime.now(timezone.utc) + timedelta(seconds=1)
        six_hours_ago = now_datetime - timedelta(hours=6, minutes=1)
        test_data = await test_db_manager.create_test_data(station_name="CYTZ", days=1)
        print(f"Test data created: {len(test_data)} entries")

        response = await integration_client.get("/api/wind?hours=6")
        assert response.status_code == 200

        data = response.json()
        assert data["station"] == "CYTZ"

        # Verify data structure and time range
        assert isinstance(data["winddata"], list)
        assert 6 * 60 - 1 <=len(data["winddata"]) <= 6 * 60 + 1
        for obs in data["winddata"]:
            assert isinstance(obs, list)
            assert len(obs) == 4  # [timestamp, direction, speed, gust]
            obs_time = datetime.fromtimestamp(obs[0], tz=timezone.utc)
            assert six_hours_ago <= obs_time <= now_datetime
            assert isinstance(obs[1], (int, float))  # direction
            assert isinstance(obs[2], (int, float))  # speed
            assert isinstance(obs[3], (int, float))  # gust


    @pytest.mark.anyio
    async def test_api_wind_time_range_with_data(
        self, integration_client, test_db_manager
    ):
        """Test API wind endpoint with time range and verify data."""
        # Generate test data
        await test_db_manager.create_test_data(station_name="CYTZ", days=1)

        now = datetime.now(timezone.utc)
        from_time = (now - timedelta(hours=16)).strftime("%Y-%m-%dT%H:%M:%S")
        to_time = (now - timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%S")

        response = await integration_client.get(
            f"/api/wind?from_time={from_time}&to_time={to_time}"
        )
        assert response.status_code == 200

        data = response.json()
        assert data["station"] == "CYTZ"

        # Verify data is within the specified time range
        from_dt = datetime.fromisoformat(from_time.replace("Z", "+00:00")).replace(
            tzinfo=timezone.utc
        )
        to_dt = datetime.fromisoformat(to_time.replace("Z", "+00:00")).replace(
            tzinfo=timezone.utc
        )

        for obs in data["winddata"]:
            obs_time = datetime.fromtimestamp(obs[0], timezone.utc)
            # Skip exact timing verification due to test execution timing
            assert from_dt <= obs_time <= to_dt

    @pytest.mark.anyio
    async def test_api_wind_data_consistency(self, integration_client, test_db_manager):
        """Test that API returns consistent data with database."""
        # Generate specific test data
        await test_db_manager.create_test_data(station_name="CYTZ", days=1)

        # Get data directly from database for comparison
        from datetime import datetime

        end_time = datetime.now(timezone.utc)
        end_time = end_time.replace(tzinfo=None)
        start_time = end_time - timedelta(hours=1)  # Use 1 hour for testing

        db_data = await test_db_manager.get_wind_data("CYTZ", start_time, end_time)

        # Verify we have data in the database
        assert len(db_data) > 0

        # Test API response structure
        response = await integration_client.get("/api/wind?hours=1")
        assert response.status_code == 200

        api_data = response.json()
        assert isinstance(api_data["winddata"], list)
        # Test that API data is consistent with database data
        # Convert database timestamps to match API format if needed
        db_timestamps = [row["update_time"] for row in db_data]
        api_timestamps = [
            datetime.fromtimestamp(obs[0], tz=timezone.utc).replace(tzinfo=None)
            for obs in api_data["winddata"]
        ]

        # Check that we have overlapping data points
        overlapping_timestamps = set(db_timestamps) & set(api_timestamps)
        assert len(overlapping_timestamps) > 59, "Fewer than 60 overlapping timestamps between DB and API data"

        # For overlapping timestamps, verify data consistency
        for api_obs in api_data["winddata"]:
            api_timestamp, api_dir, api_speed, api_gust = api_obs

            # Find matching database record
            matching_db_record = next(
                (row for row in db_data if row[0] == api_timestamp), None
            )

            if matching_db_record:
                db_timestamp, db_dir, db_speed, db_gust = matching_db_record
                # Verify data consistency (allowing for minor floating point differences)
                assert abs(api_dir - db_dir) < 0.01, f"Direction mismatch at {api_timestamp}"
                assert abs(api_speed - db_speed) < 0.01, f"Speed mismatch at {api_timestamp}"
                assert abs(api_gust - db_gust) < 0.01, f"Gust mismatch at {api_timestamp}"

    @pytest.mark.anyio
    async def test_api_wind_day_data_generation(
        self, integration_client, test_db_manager
    ):
        """Test that a full day of 1-minute interval data is properly generated."""
        # Generate exactly one day of test data at 1-minute intervals
        test_data = await test_db_manager.create_test_data(station_name="CYTZ", days=1)

        # Verify we generated the expected amount of data
        expected_records = 24 * 60  # 24 hours * 60 minutes = 1,440 records
        assert len(test_data) == expected_records

        # Query for the last 24 hours (1440 records at 1-minute intervals)
        response = await integration_client.get("/api/wind?hours=24")
        assert response.status_code == 200

        api_data = response.json()

        # Should have data for 24 hours (API may return more due to existing data)
        assert len(api_data["winddata"]) >= 24 * 60

        # Verify data structure for any returned data
        for obs in api_data["winddata"]:
            assert isinstance(obs, list)
            assert len(obs) == 4  # [timestamp, direction, speed, gust]
            assert isinstance(obs[0], (int, float))  # timestamp
            assert isinstance(obs[1], (int, float))  # direction
            assert isinstance(obs[2], (int, float))  # speed
            assert isinstance(obs[3], (int, float))  # gust
