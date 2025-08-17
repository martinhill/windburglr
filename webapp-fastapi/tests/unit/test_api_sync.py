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
    assert "day/" in response.headers["location"]


def test_historical_day_invalid_date(test_client):
    """Test historical day endpoint with invalid date."""
    response = test_client.get("/day/invalid-date")
    assert response.status_code == 400


def test_api_wind_default_params(test_client):
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


def test_api_wind_custom_station(test_client):
    """Test API wind endpoint with custom station."""
    response = test_client.get("/api/wind?stn=CYYZ")
    assert response.status_code == 200

    data = response.json()
    assert data["station"] == "CYYZ"


def test_api_wind_hours_param(test_client):
    """Test API wind endpoint with hours parameter."""
    response = test_client.get("/api/wind?hours=6")
    assert response.status_code == 200

    data = response.json()
    assert data["station"] == "CYTZ"


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
    # The endpoint doesn't support POST, so it should be 405
    assert response.status_code == 405
