from datetime import datetime, timedelta, UTC


class TestAPIEndpoints:
    """Test API endpoints with sync fixtures."""

    def test_root_endpoint(self, test_client):
        """Test root endpoint returns HTML."""
        response = test_client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "windburglr" in response.text.lower()

    def test_day_redirect(self, test_client):
        """Test day redirect endpoint."""
        response = test_client.get("/day", follow_redirects=False)
        assert response.status_code == 302
        assert "day/" in response.headers["location"]

    def test_historical_day_endpoint(self, test_client):
        """Test historical day endpoint."""
        from datetime import datetime

        today = datetime.now().strftime("%Y-%m-%d")
        response = test_client.get(f"/day/{today}")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_historical_day_invalid_date(self, test_client):
        """Test historical day endpoint with invalid date."""
        response = test_client.get("/day/invalid-date")
        assert response.status_code == 400

    def test_api_wind_default_params(self, test_client):
        """Test API wind endpoint with default parameters."""
        response = test_client.get("/api/wind")
        assert response.status_code == 200

        data = response.json()
        assert "station" in data
        assert "winddata" in data
        assert "timezone" in data
        assert "start_time" in data
        assert "end_time" in data
        assert data["station"] == "CYTZ"  # Default station

    def test_api_wind_custom_station(self, test_client):
        """Test API wind endpoint with custom station."""
        response = test_client.get("/api/wind?stn=CYYZ")
        assert response.status_code == 200

        data = response.json()
        assert data["station"] == "CYYZ"

    def test_api_wind_hours_param(self, test_client):
        """Test API wind endpoint with hours parameter."""
        response = test_client.get("/api/wind?hours=6")
        assert response.status_code == 200

        data = response.json()
        assert data["station"] == "CYTZ"

    def test_api_wind_time_range(self, test_client):
        """Test API wind endpoint with time range."""
        now = datetime.now(UTC)
        from_time = (now - timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%S")
        to_time = now.strftime("%Y-%m-%dT%H:%M:%S")

        response = test_client.get(f"/api/wind?from_time={from_time}&to_time={to_time}")
        assert response.status_code == 200

        data = response.json()
        assert data["station"] == "CYTZ"

    def test_api_wind_with_minute_interval_data(
        self, test_client, mock_test_db_manager
    ):
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
            assert isinstance(obs[1], (int, float))  # direction
            assert isinstance(obs[2], (int, float))  # speed
            assert isinstance(obs[3], (int, float))  # gust

    def test_api_wind_custom_station_with_data(self, test_client, mock_test_db_manager):
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
        if data["winddata"]:
            for obs in data["winddata"]:
                assert isinstance(obs, list)
                assert len(obs) == 4
                assert isinstance(obs[0], (int, float))  # timestamp
                assert isinstance(obs[1], (int, float))  # direction
                assert isinstance(obs[2], (int, float))  # speed
                assert isinstance(obs[3], (int, float))  # gust

    def test_api_wind_hours_param_with_generated_data(
        self, test_client, mock_test_db_manager
    ):
        """Test API wind endpoint with hours parameter using 1-minute interval data."""
        # Generate 1 day of test data at 1-minute intervals
        test_data = mock_test_db_manager.create_test_data(station_name="CYTZ", days=1)

        response = test_client.get("/api/wind?hours=6")
        assert response.status_code == 200

        data = response.json()
        assert data["station"] == "CYTZ"

        # Verify we have the expected amount of generated data (1440 records for 1 day)
        assert len(test_data) == 24 * 60

        # The API should return data within the last 6 hours
        # With 1-minute intervals, expect ~360 records for 6 hours
        for obs in data["winddata"]:
            assert isinstance(obs, list)
            assert len(obs) == 4
            assert isinstance(obs[0], (int, float))  # timestamp
            assert isinstance(obs[1], (int, float))  # direction
            assert isinstance(obs[2], (int, float))  # speed
            assert isinstance(obs[3], (int, float))  # gust

    def test_create_wind_observation_not_implemented(self, test_client):
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
