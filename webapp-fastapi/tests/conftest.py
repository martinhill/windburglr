import os

import pytest
from fastapi.testclient import TestClient


# Test database configuration
@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Set up test environment variables."""
    # Use TEST_DATABASE_URL if provided, otherwise use mock
    test_db_url = os.environ.get("TEST_DATABASE_URL")
    if test_db_url:
        os.environ["DATABASE_URL"] = test_db_url
    else:
        # Use mock database for testing
        os.environ["DATABASE_URL"] = ""


@pytest.fixture(scope="session")
def test_client():
    """Create a test client."""
    from main import app

    return TestClient(app)


@pytest.fixture
def sample_stations():
    """Provide sample station data."""
    return [
        {"name": "CYTZ", "timezone": "America/Toronto"},
        {"name": "CYYZ", "timezone": "America/Toronto"},
        {"name": "CYVR", "timezone": "America/Vancouver"},
    ]


@pytest.fixture
def mock_test_db_manager():
    """Mock database manager for testing without real database."""

    class MockTestDatabaseManager:
        def __init__(self):
            self.test_data = []

        def create_test_data(self, station_name="CYTZ", days=1):
            """Create mock test data."""
            from datetime import datetime, UTC, timedelta

            base_time = datetime.now(UTC)
            data = []
            for i in range(days * 24):
                obs_time = base_time - timedelta(hours=i)
                data.append(
                    {
                        "direction": (i * 15) % 360,
                        "speed_kts": 5 + (i % 20),
                        "gust_kts": 5 + (i % 20) + 2,
                        "update_time": obs_time,
                    }
                )
            self.test_data = data
            return data

        def get_station_data(self, station_name):
            """Mock station data."""
            return {"name": station_name, "timezone": "America/Toronto"}

    return MockTestDatabaseManager()
