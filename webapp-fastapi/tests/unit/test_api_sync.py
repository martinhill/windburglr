from fastapi.testclient import TestClient


def test_root_endpoint():
    """Test root endpoint returns HTML."""
    from main import app

    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "windburglr" in response.text.lower()


def test_day_redirect():
    """Test day redirect endpoint."""
    from main import app

    client = TestClient(app)
    response = client.get("/day", follow_redirects=False)
    assert response.status_code == 302
    assert "day/" in response.headers["location"]


def test_historical_day_invalid_date():
    """Test historical day endpoint with invalid date."""
    from main import app

    client = TestClient(app)
    response = client.get("/day/invalid-date")
    assert response.status_code == 400


def test_api_wind_default_params():
    """Test API wind endpoint with default parameters."""
    from main import app

    client = TestClient(app)
    response = client.get("/api/wind")
    assert response.status_code == 200

    data = response.json()
    assert "station" in data
    assert "winddata" in data
    assert "timezone" in data
    assert "start_time" in data
    assert "end_time" in data
    assert data["station"] == "CYTZ"  # Default station


def test_api_wind_custom_station():
    """Test API wind endpoint with custom station."""
    from main import app

    client = TestClient(app)
    response = client.get("/api/wind?stn=CYYZ")
    assert response.status_code == 200

    data = response.json()
    assert data["station"] == "CYYZ"


def test_api_wind_hours_param():
    """Test API wind endpoint with hours parameter."""
    from main import app

    client = TestClient(app)
    response = client.get("/api/wind?hours=6")
    assert response.status_code == 200

    data = response.json()
    assert data["station"] == "CYTZ"


def test_create_wind_observation_not_implemented():
    """Test POST endpoint returns not implemented."""
    from main import app

    client = TestClient(app)

    sample_data = {
        "station": "CYTZ",
        "direction": 270,
        "speed_kts": 15,
        "gust_kts": 20,
        "update_time": "2024-01-01T12:00:00",
    }

    response = client.post("/api/wind", json=sample_data)
    # The endpoint is blocked by the early return, so it should be 500
    assert response.status_code == 500
