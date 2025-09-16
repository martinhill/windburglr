import asyncio
import os
import tempfile
from datetime import datetime, UTC
from zoneinfo import ZoneInfo
from typing import Any, AsyncGenerator, Dict, Generator

import pytest
import asyncpg

from windscraper.config import Config, StationConfig
from windscraper.database import DatabaseHandler
from windscraper.models import WindObs


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def sample_station_config() -> StationConfig:
    """Sample station configuration for testing."""
    return StationConfig(
        name="TEST_STATION",
        url="https://example.com/api/test",
        timeout=10,
        headers={"User-Agent": "test-agent"},
        timezone=UTC,
        local_timezone=ZoneInfo("America/Toronto"),
    )


@pytest.fixture
def sample_config(sample_station_config: StationConfig) -> Config:
    """Sample configuration for testing."""
    return Config(
        stations=[sample_station_config],
        log_level="DEBUG",
        refresh_rate=30,
        db_url="postgresql://test:test@localhost/test_db",
        output_mode="postgres",
    )


@pytest.fixture
def sample_wind_obs() -> WindObs:
    """Sample wind observation for testing."""
    return WindObs(
        station="TEST_STATION",
        direction=180,
        speed=15.5,
        gust=20.0,
        timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
    )


@pytest.fixture
def temp_config_file(sample_config: Config) -> Generator[str, None, None]:
    """Create a temporary config file for testing."""
    config_data = """
[general]
log_level = "DEBUG"
refresh_rate = 30
db_url = "postgresql://test:test@localhost/test_db"
output_mode = "postgres"

[[stations]]
name = "TEST_STATION"
url = "https://example.com/api/test"
timeout = 10
timezone = "UTC"
local_timezone = "America/Toronto"
[stations.headers]
User-Agent = "test-agent"
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write(config_data)
        temp_path = f.name

    yield temp_path
    os.unlink(temp_path)


@pytest.fixture
async def test_db_connection() -> AsyncGenerator[asyncpg.Connection, None]:
    """Create a test database connection."""
    # Use the test database URL from environment or default
    db_url = os.getenv("TEST_DATABASE_URL", "postgresql://windburglr@/windburglr")

    conn: asyncpg.Connection = await asyncpg.connect(db_url)
    try:
        yield conn
    finally:
        await conn.close()


@pytest.fixture
async def test_database_handler(
    sample_config: Config, test_db_connection: asyncpg.Connection
) -> AsyncGenerator[DatabaseHandler, None]:
    """Create a test database handler."""
    handler = DatabaseHandler(sample_config)
    handler.conn = test_db_connection
    yield handler


@pytest.fixture
def mock_json_response() -> Dict[str, Any]:
    """Mock JSON response from the wind API."""
    return {
        "v2": {
            "sensor_data": {
                "TEST_STATION": {
                    "wind_magnetic_dir_2_mean": "180",
                    "wind_speed_2_mean": "15.5",
                    "gust_squall_speed": "20.0",
                    "observation_time": "2024-01-01 12:00",
                }
            }
        }
    }


@pytest.fixture
def mock_raw_json_data(mock_json_response: Dict[str, Any]) -> str:
    """Mock raw JSON data as string."""
    import json

    return json.dumps(mock_json_response)


@pytest.fixture
def mock_aiohttp_session():
    """Mock aiohttp ClientSession for testing."""

    class MockResponse:
        def __init__(self, text: str, status: int = 200):
            self._text = text
            self.status = status

        async def text(self) -> str:
            return self._text

        def raise_for_status(self):
            if self.status >= 400:
                raise Exception(f"HTTP {self.status}")

    class MockSession:
        def __init__(self, response_text: str, status: int = 200):
            self.response_text = response_text
            self.status = status

        async def get(self, url: str, timeout=None, headers=None):
            return MockResponse(self.response_text, self.status)

        async def close(self):
            pass

    return MockSession


@pytest.fixture
def mock_observation_tracker():
    """Mock observation tracker for testing."""

    class MockTracker:
        def __init__(self):
            self.last_obs_time: Dict[str, datetime] = {}

        def is_new_obs(self, obs: WindObs) -> bool:
            return True

        def set_obs_last_timestamp(self, obs: WindObs):
            self.last_obs_time[obs.station] = obs.timestamp

    return MockTracker()


@pytest.fixture
def mock_retry_handler():
    """Mock retry handler for testing."""

    class MockRetryHandler:
        def __init__(self):
            self.call_count = 0

        async def execute_with_retry(self, func: Any, *args: Any, **kwargs: Any) -> Any:
            self.call_count += 1
            return await func(*args, **kwargs)

    return MockRetryHandler()
