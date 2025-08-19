import os
import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport
from httpx_ws.transport import ASGIWebSocketTransport
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any
from contextlib import asynccontextmanager


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


@pytest.fixture
def sample_stations():
    """Provide sample station data."""
    return [
        {"name": "CYTZ", "timezone": "America/Toronto"},
        {"name": "CYYZ", "timezone": "America/Toronto"},
        {"name": "CYVR", "timezone": "America/Vancouver"},
    ]


@pytest.fixture
async def test_db_manager():
    """Real database manager for integration tests."""
    import asyncpg

    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL not set - skipping real database tests")

    class TestDatabaseManager:
        """Real database manager for integration testing."""

        def __init__(self):
            self.pool = None
            self.test_connection = None
            self.test_transaction = None

        async def setup(self, database_url):
            """Initialize database connection pool and test transaction."""
            self.database_url = database_url
            try:
                self.pool = await asyncpg.create_pool(self.database_url)
                await self.create_schema()

                # Get dedicated connection for this test
                self.test_connection = await self.pool.acquire()
                # Start transaction that will be rolled back after test
                self.test_transaction = self.test_connection.transaction()
                await self.test_transaction.start()

                return True
            except Exception as e:
                print(f"Failed to connect to database: {e}")
                return False

        async def cleanup(self):
            """Clean up test transaction and database connection."""
            if self.test_transaction:
                await self.test_transaction.rollback()
            if self.test_connection:
                await self.pool.release(self.test_connection)
            if self.pool:
                await self.pool.close()

        async def create_schema(self):
            """Create test database schema (outside of test transaction)."""
            async with self.pool.acquire() as conn:
                # Create extensions
                await conn.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")

                # Create station table
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS station (
                        id SERIAL PRIMARY KEY,
                        name VARCHAR(10) UNIQUE NOT NULL,
                        timezone VARCHAR(50) NOT NULL DEFAULT 'UTC'
                    )
                """)

                # Create wind_obs table
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS wind_obs (
                        station_id INTEGER REFERENCES station(id),
                        update_time TIMESTAMP NOT NULL,
                        direction NUMERIC,
                        speed_kts NUMERIC,
                        gust_kts NUMERIC,
                        PRIMARY KEY (station_id, update_time)
                    )
                """)

                # Create hypertable
                try:
                    await conn.execute(
                        "SELECT create_hypertable('wind_obs', 'update_time')"
                    )
                except:
                    # Hypertable might already exist
                    pass

        async def create_test_stations(self, stations_data):
            await self.test_connection.executemany(
                """
                INSERT INTO station (name, timezone)
                VALUES ($1, $2)
                ON CONFLICT (name) DO UPDATE SET timezone = EXCLUDED.timezone
                RETURNING id
                """,
                ((station["name"], station["timezone"]) for station in stations_data),
            )

        async def create_test_data(
            self, station_name="CYTZ", timezone_name="America/Toronto", days=1
        ):
            """Create test data within the test transaction."""
            # Insert station if not exists
            station_id = await self.test_connection.fetchval(
                """
                INSERT INTO station (name, timezone)
                VALUES ($1, $2)
                ON CONFLICT (name) DO UPDATE SET timezone = EXCLUDED.timezone
                RETURNING id
                """,
                station_name,
                timezone_name,
            )

            # Generate test data at 1-minute intervals
            base_time = datetime.now(timezone.utc)
            data = []

            # Generate data for the specified number of days at 1-minute intervals
            total_minutes = days * 24 * 60
            for i in range(total_minutes):
                obs_time = (base_time - timedelta(minutes=i)).replace(tzinfo=None)
                hour_of_day = obs_time.hour

                # Create more realistic wind patterns
                direction = (
                    int(obs_time.timestamp() / 360) % 360
                )  # Gradual direction changes

                # Simulate realistic wind speeds with some variation
                base_speed = 8 + (hour_of_day % 12)  # Varies by time of day
                speed_kts = max(0, base_speed + (i % 7) - 3)  # Add some randomness
                gust_kts = speed_kts + max(
                    1, (i % 5)
                )  # Gust is typically 1-5 kts above speed

                await self.test_connection.execute(
                    """
                    INSERT INTO wind_obs (station_id, update_time, direction, speed_kts, gust_kts)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    station_id,
                    obs_time,
                    direction,
                    speed_kts,
                    gust_kts,
                )

                data.append(
                    {
                        "direction": direction,
                        "speed_kts": speed_kts,
                        "gust_kts": gust_kts,
                        "update_time": obs_time,
                    }
                )

            return data

        async def insert_new_wind_obs(
            self, station_name: str, direction: int, speed_kts: int, gust_kts: int, obs_time: datetime
        ):
            await self.test_connection.execute(
                """
                INSERT INTO wind_obs (station_id, direction, speed_kts, gust_kts, update_time)
                VALUES ((SELECT id FROM station WHERE name = $1), $2, $3, $4, $5)
                """,
                station_name,
                direction,
                speed_kts,
                gust_kts,
                obs_time,
            )

        async def get_station_timezone(self, station_name):
            """Get station timezone within test transaction."""
            result = await self.test_connection.fetchval(
                "SELECT timezone FROM station WHERE name = $1", station_name
            )
            return result or "UTC"

        async def get_wind_data(self, station_name, start_time, end_time):
            """Get wind data within test transaction."""
            return await self.test_connection.fetch(
                """
                SELECT w.direction, w.speed_kts, w.gust_kts, w.update_time
                FROM wind_obs w
                JOIN station s ON w.station_id = s.id
                WHERE s.name = $1 AND w.update_time >= $2 AND w.update_time <= $3
                ORDER BY w.update_time DESC
                """,
                station_name,
                start_time,
                end_time,
            )

    # Create and setup manager
    manager = TestDatabaseManager()
    setup_success = await manager.setup(database_url)
    if not setup_success:
        pytest.skip("Could not connect to test database")

    try:
        yield manager
    finally:
        await manager.cleanup()


@pytest.fixture
def mock_test_db_manager():
    """Mock database manager for testing without real database."""

    class MockTestDatabaseManager:
        def __init__(self):
            self.test_data = []

        def create_test_data(self, station_name="CYTZ", days=1):
            """Create mock test data at 1-minute intervals."""
            base_time = datetime.now(timezone.utc)
            data = []
            total_minutes = days * 24 * 60

            for i in range(total_minutes):
                obs_time = base_time - timedelta(minutes=i)
                hour_of_day = obs_time.hour

                # Create more realistic wind patterns
                direction = int(obs_time.timestamp() / 360) % 360
                base_speed = 8 + (hour_of_day % 12)
                speed_kts = max(0, base_speed + (i % 7) - 3)
                gust_kts = speed_kts + max(1, (i % 5))

                data.append(
                    {
                        "direction": direction,
                        "speed_kts": speed_kts,
                        "gust_kts": gust_kts,
                        "update_time": obs_time,
                        "station": station_name,
                    }
                )
            self.test_data = data
            return data

        def get_station_data(self, station_name):
            """Mock station data."""
            return {"name": station_name, "timezone": "America/Toronto"}

        def cleanup(self):
            self.test_data = None

    manager = MockTestDatabaseManager()

    try:
        yield manager
    finally:
        manager.cleanup()


class WindDataGenerator:
    """Generate realistic test wind data."""

    @staticmethod
    def generate_hourly_data(
        station: str = "CYTZ",
        hours: int = 24,
        base_direction: int = 270,
        base_speed: int = 10,
        gust_variance: int = 5,
    ) -> List[Dict[str, Any]]:
        """Generate hourly wind data."""
        data = []
        now = datetime.now(timezone.utc)

        for i in range(hours):
            timestamp = now - timedelta(hours=i)

            # Add some realistic variation
            direction = base_direction + (i % 30) - 15  # ±15° variation
            speed = base_speed + (i % 8) - 4  # ±4 kts variation
            gust = speed + (i % gust_variance) + 2  # Gust 2-7 kts above speed

            data.append(
                {
                    "station": station,
                    "direction": direction % 360,
                    "speed_kts": max(0, speed),
                    "gust_kts": max(0, gust),
                    "update_time": timestamp,
                }
            )

        return data

    @staticmethod
    def generate_storm_data(
        station: str = "CYTZ", duration_hours: int = 6, max_speed: int = 45
    ) -> List[Dict[str, Any]]:
        """Generate storm condition data."""
        data = []
        now = datetime.now(timezone.utc)

        for i in range(duration_hours):
            timestamp = now - timedelta(hours=i)

            # Build up to storm
            if i < 2:
                speed = 15 + (i * 5)
            elif i < 4:
                speed = 25 + (i * 3)
            else:
                speed = max_speed - (i * 2)

            gust = speed + 10
            direction = 180 + (i * 20)  # Shifting winds

            data.append(
                {
                    "station": station,
                    "direction": direction % 360,
                    "speed_kts": speed,
                    "gust_kts": gust,
                    "update_time": timestamp,
                }
            )

        return data

    @staticmethod
    def generate_calm_data(
        station: str = "CYTZ", duration_hours: int = 12
    ) -> List[Dict[str, Any]]:
        """Generate calm wind conditions."""
        data = []
        now = datetime.now(timezone.utc)

        for i in range(duration_hours):
            timestamp = now - timedelta(hours=i)

            # Very light winds
            speed = 2 + (i % 3)  # 2-4 kts
            gust = speed + 1
            direction = 0  # Variable/Calm

            data.append(
                {
                    "station": station,
                    "direction": direction,
                    "speed_kts": speed,
                    "gust_kts": gust,
                    "update_time": timestamp,
                }
            )

        return data


@pytest.fixture
def test_client(mock_test_db_manager):
    """Create a test client for unit tests that uses mock_test_db_manager."""
    from main import app, get_db_pool

    class MockConnection:
        """Mock database connection that uses mock_test_db_manager data."""

        def __init__(self, mock_manager):
            self.mock_manager = mock_manager

        async def fetch(self, query, *args):
            """Mock fetch method that returns data from mock_test_db_manager."""
            from datetime import datetime, timezone, timedelta

            if "get_wind_data_by_station_range" in query.lower():
                # Return data from mock_test_db_manager
                station = args[0] if len(args) > 0 else "CYTZ"

                # Use the mock manager's test data
                test_data = self.mock_manager.test_data

                # Filter and format data for API response
                filtered_data = []
                for obs in test_data:
                    if obs.get("station", station) == station:
                        filtered_data.append(
                            {
                                "update_time": obs["update_time"],
                                "direction": obs["direction"],
                                "speed_kts": obs["speed_kts"],
                                "gust_kts": obs["gust_kts"],
                            }
                        )
                return filtered_data

            if "station" in query.lower():
                # Return mock station data
                station_name = args[0] if args else "CYTZ"
                return [{"name": station_name, "timezone_name": "America/Toronto"}]

            return []

        async def fetchrow(self, query, *args):
            """Mock fetchrow method for single row queries."""

            if "get_latest_wind_observation" in query.lower():
                station = args[0] if args else "CYTZ"
                test_data = self.mock_manager.test_data
                if test_data:
                    # Return the most recent observation
                    latest = test_data[0]  # Assuming sorted by time
                    return {
                        "direction": latest["direction"],
                        "speed_kts": latest["speed_kts"],
                        "gust_kts": latest["gust_kts"],
                        "update_time": latest["update_time"],
                        "name": latest.get("station", station),
                    }

            if "station" in query.lower() and "timezone" in query.lower():
                return {"timezone_name": "America/Toronto"}

            return None

        async def fetchval(self, query, *args):
            """Mock fetchval method for single value queries."""
            if "get_station_timezone_name" in query.lower():
                return "America/Toronto"
            return None

    class MockPool:
        """Mock database pool that returns mock data."""

        def __init__(self, mock_manager):
            self.mock_manager = mock_manager

        @asynccontextmanager
        async def acquire(self):
            """Mock acquire method that yields a mock connection."""
            yield MockConnection(self.mock_manager)

    mock_pool = MockPool(mock_test_db_manager)

    async def get_mock_data_source():
        return mock_pool

    app.dependency_overrides[get_db_pool] = get_mock_data_source
    yield TestClient(app)


class TestPool:
    """Mock pool that returns the test connection from test_db_manager."""

    def __init__(self, connection):
        self.connection = connection

    @asynccontextmanager
    async def acquire(self):
        yield self.connection


@pytest.fixture
async def integration_client(test_db_manager):
    """Create a test client with real database for integration tests."""
    from main import app, get_db_pool

    test_pool = TestPool(test_db_manager.test_connection)

    async def get_real_data_source():
        return test_pool

    app.dependency_overrides[get_db_pool] = get_real_data_source
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        yield client


@pytest.fixture
async def ws_integration_client(test_db_manager):
    """Create a test client with real database for integration tests."""
    from main import app, get_db_pool

    test_pool = TestPool(test_db_manager.test_connection)

    async def get_real_data_source():
        return test_pool

    app.dependency_overrides[get_db_pool] = get_real_data_source
    async with AsyncClient(transport=ASGIWebSocketTransport(app=app), base_url="http://testserver") as client:
        yield client


@pytest.fixture
def wind_data_generator():
    """Provide wind data generator."""
    return WindDataGenerator()


@pytest.fixture
def anyio_backend():
    return "asyncio"
