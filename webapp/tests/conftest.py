import logging
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from asgi_lifespan import LifespanManager
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from httpx_ws.transport import ASGIWebSocketTransport

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


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
            self.test_stations = set()  # Track test stations for cleanup
            self.test_wind_data = []  # Track test data for cleanup

        @property
        def latest_wind_obs(self):
            # Find item in self.test_wind_data with the maximum value in key "update_time"
            return max(self.test_wind_data, key=lambda x: x["update_time"])

        async def setup(self, database_url):
            """Initialize database connection pool."""
            self.database_url = database_url
            try:
                self.pool = await asyncpg.create_pool(self.database_url)
                return True
            except Exception as e:
                print(f"Failed to connect to database: {e}")
                return False

        async def cleanup(self):
            """Clean up all test data from tables."""
            if self.pool:
                async with self.pool.acquire() as conn:
                    # Delete all wind observations for test stations
                    if self.test_stations:
                        station_names = list(self.test_stations)
                        await conn.execute(
                            "DELETE FROM wind_obs WHERE station_id IN (SELECT id FROM station WHERE name = ANY($1))",
                            station_names,
                        )
                        # Delete test stations
                        await conn.execute(
                            "DELETE FROM station WHERE name = ANY($1)",
                            station_names,
                        )
                    self.test_stations.clear()
                await self.pool.close()

        async def create_test_stations(self, stations_data):
            async with self.pool.acquire() as conn:
                await conn.executemany(
                    """
                    INSERT INTO station (name, timezone)
                    VALUES ($1, $2)
                    ON CONFLICT (name) DO UPDATE SET timezone = EXCLUDED.timezone
                    RETURNING id
                    """,
                    (
                        (station["name"], station["timezone"])
                        for station in stations_data
                    ),
                )
                # Track stations for cleanup
                for station in stations_data:
                    self.test_stations.add(station["name"])

        async def create_test_data(
            self, station_name="CYTZ", timezone_name="America/Toronto", days=1
        ):
            """Create test data."""
            async with self.pool.acquire() as conn:
                # Insert station
                station_id = await conn.fetchval(
                    """
                    INSERT INTO station (name, timezone)
                    VALUES ($1, $2)
                    ON CONFLICT (name) DO UPDATE SET timezone = EXCLUDED.timezone
                    RETURNING id
                    """,
                    station_name,
                    timezone_name,
                )

                # Track station for cleanup
                self.test_stations.add(station_name)

                # Generate test data at 1-minute intervals
                base_time = datetime.now(UTC)
                data = []

                # Generate data for the specified number of days at 1-minute intervals
                total_minutes = days * 24 * 60
                for i in range(total_minutes):
                    obs_time = base_time - timedelta(minutes=i)
                    hour_of_day = obs_time.hour

                    # Create more realistic wind patterns
                    direction = (
                        int(obs_time.timestamp() / 360) % 360
                    )  # Gradual direction changes

                    # Simulate realistic wind speeds with some variation
                    base_speed = 5 + (hour_of_day % 12)  # Varies by time of day
                    speed_kts = max(0, base_speed + (i % 7) - 3)  # Add some randomness
                    if speed_kts == 0:
                        direction = None
                    gust_kts = speed_kts + max(
                        speed_kts + 2, speed_kts + (i % 5)
                    )  # Gust is typically 1-5 kts above speed
                    if gust_kts == speed_kts + 2:
                        gust_kts = None

                    await conn.execute(
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

                    obs = {
                        "station_name": station_name,
                        "direction": direction,
                        "speed_kts": speed_kts,
                        "gust_kts": gust_kts,
                        "update_time": obs_time,
                    }
                    self.test_wind_data.append(obs)
                    data.append(obs)

                return data

        async def create_bulk_test_data(
            self, station_name="CYTZ", timezone_name="America/Toronto", days=1
        ):
            """Create test data in bulk without triggering notifications (for use before app startup)."""
            async with self.pool.acquire() as conn:
                # Temporarily disable the trigger to avoid notification spam
                await conn.execute(
                    "DROP TRIGGER IF EXISTS wind_obs_insert_trigger ON wind_obs"
                )

                try:
                    # Insert station
                    station_id = await conn.fetchval(
                        """
                        INSERT INTO station (name, timezone)
                        VALUES ($1, $2)
                        ON CONFLICT (name) DO UPDATE SET timezone = EXCLUDED.timezone
                        RETURNING id
                        """,
                        station_name,
                        timezone_name,
                    )

                    # Track station for cleanup
                    self.test_stations.add(station_name)

                    # Generate bulk data for insertion
                    base_time = datetime.now(UTC)
                    data_rows = []

                    # Generate data for the specified number of days at 1-minute intervals
                    total_minutes = days * 24 * 60
                    for i in range(total_minutes):
                        obs_time = base_time - timedelta(minutes=i)
                        hour_of_day = obs_time.hour

                        # Create more realistic wind patterns
                        direction = (
                            int(obs_time.timestamp() / 360) % 360
                        )  # Gradual direction changes

                        # Simulate realistic wind speeds with some variation
                        base_speed = 8 + (hour_of_day % 12)  # Varies by time of day
                        speed_kts = max(
                            0, base_speed + (i % 7) - 3
                        )  # Add some randomness
                        gust_kts = speed_kts + max(
                            1, (i % 5)
                        )  # Gust is typically 1-5 kts above speed

                        data_rows.append(
                            (station_id, obs_time, direction, speed_kts, gust_kts)
                        )
                        self.test_wind_data.append(
                            {
                                "station_name": station_name,
                                "update_time": obs_time,
                                "direction": direction,
                                "speed_kts": speed_kts,
                                "gust_kts": gust_kts,
                            }
                        )

                    # Bulk insert all data at once
                    await conn.executemany(
                        """
                        INSERT INTO wind_obs (station_id, update_time, direction, speed_kts, gust_kts)
                        VALUES ($1, $2, $3, $4, $5)
                        """,
                        data_rows,
                    )

                    # Return summary data for validation
                    return {
                        "station_name": station_name,
                        "station_id": station_id,
                        "rows_inserted": len(data_rows),
                        "time_range": (data_rows[-1][1], data_rows[0][1])
                        if data_rows
                        else None,
                    }

                finally:
                    # Always restore the trigger
                    await conn.execute("""
                        CREATE TRIGGER wind_obs_insert_trigger
                            AFTER INSERT ON wind_obs
                            FOR EACH ROW
                            EXECUTE FUNCTION notify_wind_obs_insert()
                    """)

        async def insert_new_wind_obs(
            self,
            station_name: str,
            direction: int,
            speed_kts: int,
            gust_kts: int,
            obs_time: datetime,
        ):
            # Insert wind observation to trigger PostgreSQL notifications
            async with self.pool.acquire() as conn:
                # Get station_id first
                station_id = await conn.fetchval(
                    "SELECT id FROM station WHERE name = $1", station_name
                )
                if not station_id:
                    raise ValueError(f"Station {station_name} not found")

                # Insert with commit to trigger wind_obs_insert_trigger
                await conn.execute(
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

                # Track station for cleanup
                self.test_stations.add(station_name)

        async def get_station_timezone(self, station_name):
            """Get station timezone."""
            async with self.pool.acquire() as conn:
                result = await conn.fetchval(
                    "SELECT timezone FROM station WHERE name = $1", station_name
                )
                return result or "UTC"

        async def get_wind_data(self, station_name, start_time, end_time):
            """Get wind data."""
            async with self.pool.acquire() as conn:
                return await conn.fetch(
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

        async def create_scraper_status(
            self,
            station_name: str,
            status: str = "active",
            last_success_minutes_ago: int = 5,
            last_attempt_minutes_ago: int = 1,
            error_message: str = None,
            retry_count: int = 0,
        ):
            """Create or update scraper status for a station."""
            async with self.pool.acquire() as conn:
                # Ensure station exists first
                station_id = await conn.fetchval(
                    """
                    INSERT INTO station (name, timezone)
                    VALUES ($1, 'UTC')
                    ON CONFLICT (name) DO UPDATE SET timezone = EXCLUDED.timezone
                    RETURNING id
                    """,
                    station_name,
                )

                # Track station for cleanup
                self.test_stations.add(station_name)

                # Calculate timestamps
                now = datetime.now(UTC)
                last_success = (
                    now - timedelta(minutes=last_success_minutes_ago)
                    if last_success_minutes_ago is not None
                    else None
                )
                last_attempt = (
                    now - timedelta(minutes=last_attempt_minutes_ago)
                    if last_attempt_minutes_ago is not None
                    else None
                )

                # Insert or update scraper status
                await conn.execute(
                    """
                    INSERT INTO scraper_status (station_id, status, last_success, last_attempt, error_message, retry_count, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT (station_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        last_success = EXCLUDED.last_success,
                        last_attempt = EXCLUDED.last_attempt,
                        error_message = EXCLUDED.error_message,
                        retry_count = EXCLUDED.retry_count,
                        updated_at = EXCLUDED.updated_at
                    """,
                    station_id,
                    status,
                    last_success,
                    last_attempt,
                    error_message,
                    retry_count,
                    now,
                )

                return {
                    "station_name": station_name,
                    "station_id": station_id,
                    "status": status,
                    "last_success": last_success,
                    "last_attempt": last_attempt,
                    "error_message": error_message,
                    "retry_count": retry_count,
                }

        async def update_scraper_status(
            self, station_name: str, status: str, error_message: str = None
        ):
            """Update scraper status using the database function (triggers notification)."""
            async with self.pool.acquire() as conn:
                await conn.execute(
                    "SELECT update_scraper_status($1, $2, $3)",
                    station_name,
                    status,
                    error_message,
                )

        async def get_scraper_status(self, station_name: str = None):
            """Get scraper status for station(s)."""
            async with self.pool.acquire() as conn:
                if station_name:
                    # Get status for specific station
                    result = await conn.fetchrow(
                        """
                        SELECT s.name as station_name,
                               COALESCE(ss.status, 'unknown') as status,
                               ss.last_success,
                               ss.last_attempt,
                               ss.error_message,
                               ss.retry_count,
                               ss.updated_at
                        FROM station s
                        LEFT JOIN scraper_status ss ON s.id = ss.station_id
                        WHERE s.name = $1
                        """,
                        station_name,
                    )
                    return dict(result) if result else None
                else:
                    # Get status for all stations
                    results = await conn.fetch(
                        """
                        SELECT s.name as station_name,
                               COALESCE(ss.status, 'unknown') as status,
                               ss.last_success,
                               ss.last_attempt,
                               ss.error_message,
                               ss.retry_count,
                               ss.updated_at
                        FROM station s
                        LEFT JOIN scraper_status ss ON s.id = ss.station_id
                        ORDER BY s.name
                        """
                    )
                    return [dict(row) for row in results]

    # Create and setup manager
    manager = TestDatabaseManager()
    setup_success = await manager.setup(database_url)
    if not setup_success:
        pytest.skip(f"Could not connect to test database {database_url}")

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
            # Add a list to store recorded queries
            self.recorded_queries = []

        def create_test_data(self, station_name="CYTZ", days=1):
            """Create mock test data at 1-minute intervals."""
            base_time = datetime.now(UTC) - timedelta(days=days)
            data = []
            total_minutes = days * 24 * 60

            for i in range(total_minutes):
                obs_time = base_time + timedelta(minutes=i)
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
            if self.test_data is None:
                self.test_data = []
            self.test_data.extend(data)
            return data

        def get_station_data(self, station_name):
            """Mock station data."""
            return {"name": station_name, "timezone": "America/Toronto"}

        def record_query(self, method, query, args):
            """Record a query execution with its parameters."""
            logger.debug("Recording query: %s, Args: %s", query, args)
            self.recorded_queries.append(
                {
                    "method": method,
                    "query": query,
                    "args": args,
                    "timestamp": datetime.now(UTC),
                }
            )

        def get_recorded_queries(self, method=None, contains=None):
            """
            Get recorded queries with optional filtering.

            Args:
                method: Filter by method name (fetch, fetchrow, fetchval)
                contains: Filter queries containing this string

            Returns:
                List of matching query records
            """
            result = self.recorded_queries

            if method:
                result = [q for q in result if q["method"] == method]

            if contains:
                result = [q for q in result if contains in q["query"]]

            return result

        def clear_recorded_queries(self):
            """Clear all recorded queries."""
            self.recorded_queries = []

        @property
        def query_count(self):
            """Get the total number of recorded queries."""
            return len(self.recorded_queries)

        def create_test_stations(self, stations_data):
            """Create stations for testing (mock implementation)."""
            # Mock implementation - just store in test_data
            for station in stations_data:
                station_name = station["name"]
                # Add mock scraper status for each station
                self.test_data.append(
                    {"station": station_name, "scraper_status": "active"}
                )

        def cleanup(self):
            self.test_data = None
            self.recorded_queries = []

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
    ) -> list[dict[str, Any]]:
        """Generate hourly wind data."""
        data = []
        now = datetime.now(UTC)

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
    ) -> list[dict[str, Any]]:
        """Generate storm condition data."""
        data = []
        now = datetime.now(UTC)

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
    ) -> list[dict[str, Any]]:
        """Generate calm wind conditions."""
        data = []
        now = datetime.now(UTC)

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
def test_client(request, mock_test_db_manager):
    """Create a test client for unit tests that uses mock_test_db_manager."""
    # Get configuration overrides from request.param, defaulting to 60.0
    config_overrides = getattr(request, "param", {})
    websocket_timeout = config_overrides.get("websocket_timeout", 60.0)
    import asyncio
    import json

    from app.dependencies import get_db_pool, get_websocket_config
    from main import make_app

    class MockListenerConnection:
        """Mock asyncpg.Connection that supports listeners for testing."""

        def __init__(self, mock_manager):
            self.mock_manager = mock_manager
            self._listeners = {}
            self._closed = False

        def is_closed(self):
            return self._closed

        async def close(self):
            # Don't actually close for testing purposes
            # self._closed = True
            pass

        async def fetchval(self, query, *args):
            """Mock fetchval for health checks."""
            if query == "SELECT 1":
                return 1
            return None

        async def fetch(self, query, *args):
            """Mock fetch method - delegate to the mock connection."""
            mock_connection = MockConnection(self.mock_manager)
            return await mock_connection.fetch(query, *args)

        async def add_listener(self, channel, callback):
            """Mock add_listener to register notification handlers."""
            self._listeners[channel] = callback

        async def trigger_notification(self, channel, payload_data):
            """Test helper to trigger notifications to registered listeners."""
            if channel in self._listeners:
                # Simulate the asyncpg notification format
                payload = json.dumps(payload_data)
                logger.debug(
                    "Triggering notification for channel %s: %s", channel, payload
                )
                await self._listeners[channel](self, 12345, channel, payload)

    class MockPool:
        """Mock database connection pool that uses mock_test_db_manager data."""

        def __init__(self, mock_manager):
            self.mock_manager = mock_manager

        @asynccontextmanager
        async def acquire(self):
            """Mock acquire method that returns a mock connection."""
            yield MockConnection(self.mock_manager)

        # async def fetchval(self, query, *args):
        #     """Mock fetchval method."""
        #     async with self.acquire() as conn:
        #         return await conn.fetchval(query, *args)

        # async def fetch(self, query, *args):
        #     """Mock fetch method."""
        #     async with self.acquire() as conn:
        #         return await conn.fetch(query, *args)

        # async def fetchrow(self, query, *args):
        #     """Mock fetchrow method."""
        #     async with self.acquire() as conn:
        #         return await conn.fetchrow(query, *args)

    class MockConnection:
        """Mock database connection that uses mock_test_db_manager data."""

        def __init__(self, mock_manager):
            self.mock_manager = mock_manager

        async def fetch(self, query, *args):
            """Mock fetch method that returns data from mock_test_db_manager."""
            # Record the query
            self.mock_manager.record_query("fetch", query, args)

            if "get_scraper_status" in query.lower():
                logger.debug("Mocking scraper status data")
                # Return mock scraper status data based on test data
                now = datetime.now(UTC)
                test_data = self.mock_manager.test_data
                stations_with_scraper_status = []

                # Check if we have stations with scraper_status info
                if test_data:
                    stations_with_data = [
                        item for item in test_data if "scraper_status" in item
                    ]

                    for item in stations_with_data:
                        station_name = item.get("station", "CYTZ")
                        stations_with_scraper_status.append(
                            {
                                "station_name": station_name,
                                "status": item.get("scraper_status", "unknown"),
                                "last_success": (
                                    now - timedelta(minutes=5)
                                ).isoformat(),
                                "last_attempt": (
                                    now - timedelta(minutes=1)
                                ).isoformat(),
                                "error_message": None,
                                "retry_count": 0,
                                "updated_at": now.isoformat(),
                                "time_since_last_attempt": "0:01:00",
                                "time_since_last_success": "0:05:00",
                            }
                        )

                # For stations that have wind data but no explicit scraper status, assume "active"
                stations_with_wind_data = set()
                if test_data:
                    for item in test_data:
                        if (
                            "direction" in item and "speed_kts" in item
                        ):  # Wind observation
                            stations_with_wind_data.add(item.get("station", "CYTZ"))

                existing_stations = {
                    s["station_name"] for s in stations_with_scraper_status
                }
                for station_name in stations_with_wind_data - existing_stations:
                    stations_with_scraper_status.append(
                        {
                            "station_name": station_name,
                            "status": "active",  # Default to active for stations with wind data
                            "last_success": (now - timedelta(minutes=5)).isoformat(),
                            "last_attempt": (now - timedelta(minutes=1)).isoformat(),
                            "error_message": None,
                            "retry_count": 0,
                            "updated_at": now.isoformat(),
                            "time_since_last_attempt": "0:01:00",
                            "time_since_last_success": "0:05:00",
                        }
                    )

                # For stations created without wind data (create_test_stations), add "unknown" status
                all_stations = set()
                logger.debug("all_stations %s", str(all_stations))
                if test_data:
                    for item in test_data:
                        if "station" in item:
                            all_stations.add(item["station"])

                stations_without_wind = (
                    all_stations - stations_with_wind_data - existing_stations
                )
                for station_name in stations_without_wind:
                    stations_with_scraper_status.append(
                        {
                            "station_name": station_name,
                            "status": "unknown",
                            "last_success": None,
                            "last_attempt": None,
                            "error_message": None,
                            "retry_count": 0,
                            "updated_at": None,
                            "time_since_last_attempt": None,
                            "time_since_last_success": None,
                        }
                    )

                logger.debug(
                    "Returning stations_with_scraper_status %s",
                    str(stations_with_scraper_status),
                )
                return stations_with_scraper_status

            if "get_wind_data_by_station_range" in query.lower():
                # Return data from mock_test_db_manager
                station = args[0] if len(args) > 0 else "CYTZ"
                start_time = args[1] if len(args) > 1 else None
                end_time = args[2] if len(args) > 2 else None

                # Use the mock manager's test data
                test_data = self.mock_manager.test_data

                # Filter and format data for API response
                filtered_data = []
                for obs in test_data:
                    if obs.get("station", station) == station:
                        # Filter by time range if provided
                        if start_time and end_time:
                            # Convert timezone-aware start_time and end_time to timezone-naive for comparison
                            if not (start_time <= obs["update_time"] <= end_time):
                                continue
                        filtered_data.append(
                            {
                                "update_time": obs["update_time"],
                                "direction": obs["direction"],
                                "speed_kts": obs["speed_kts"],
                                "gust_kts": obs["gust_kts"],
                            }
                        )
                logger.debug(
                    "Mocking fetch (%s, %s, %s): %d",
                    station,
                    start_time,
                    end_time,
                    len(filtered_data),
                )

                return filtered_data

            if "station" in query.lower():
                # Return mock station data
                station_name = args[0] if args else "CYTZ"
                return [{"name": station_name, "timezone_name": "America/Toronto"}]

            return []

        async def fetchrow(self, query, *args):
            """Mock fetchrow method for single row queries."""
            # Record the query
            self.mock_manager.record_query("fetchrow", query, args)

            if "get_latest_wind_observation" in query.lower():
                station = args[0] if args else "CYTZ"
                test_data = self.mock_manager.test_data
                if test_data:
                    # Look for wind observations for this specific station
                    wind_observations = [
                        item
                        for item in test_data
                        if all(
                            key in item
                            for key in ["direction", "speed_kts", "gust_kts"]
                        )
                        and item.get("station") == station
                    ]
                    if wind_observations:
                        # Return the most recent observation
                        latest = wind_observations[0]  # Assuming sorted by time
                        return {
                            "direction": latest["direction"],
                            "speed_kts": latest["speed_kts"],
                            "gust_kts": latest["gust_kts"],
                            "update_time": latest["update_time"],
                            "name": latest.get("station", station),
                        }
                # No wind data available
                return None

            if "station" in query.lower() and "timezone" in query.lower():
                return {"timezone_name": "America/Toronto"}

            return None

        async def fetchval(self, query, *args):
            """Mock fetchval method for single value queries."""
            # Record the query
            self.mock_manager.record_query("fetchval", query, args)

            if "get_station_timezone_name" in query.lower():
                return "America/Toronto"
            return None

    mock_pool = MockPool(mock_test_db_manager)
    mock_listener_conn = MockListenerConnection(mock_test_db_manager)

    async def get_mock_pool():
        return mock_pool

    async def get_mock_websocket_config():
        return {"ping_timeout": websocket_timeout}

    # Create app with injected mock listener connection
    app = make_app(pg_connection=mock_listener_conn)
    app.dependency_overrides[get_db_pool] = get_mock_pool
    app.dependency_overrides[get_websocket_config] = get_mock_websocket_config

    # Use LifespanManager to properly start the app and register listeners
    async def start_app():
        async with LifespanManager(app) as manager_app:
            # Create test client with the actual FastAPI app from the manager
            client = TestClient(manager_app.app)
            # Store reference to the mock connection for direct access
            client.mock_listener_connection = mock_listener_conn
            return client

    # Run the async startup and return the client
    return asyncio.run(start_app())


@pytest.fixture
async def set_env_database_url():
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]


@pytest.fixture
async def persistent_connection():
    """Provide a persistent database connection for the listener."""
    import asyncpg
    # from main import manager

    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL not set - skipping real database tests")

    connection = await asyncpg.connect(database_url)
    # manager.set_pg_listener(connection)

    yield connection

    await connection.close()


@pytest.fixture
async def test_db_with_bulk_data(test_db_manager):
    """Fixture that creates bulk test data BEFORE app startup to avoid notification spam."""
    # Create bulk historical data without triggering notifications
    await test_db_manager.create_bulk_test_data(station_name="CYTZ", days=7)
    yield test_db_manager


@pytest.fixture
async def app(test_db_manager, persistent_connection):
    from app.dependencies import get_db_pool
    from main import make_app

    async def get_test_db_pool():
        return test_db_manager.pool

    app = make_app(persistent_connection)
    app.dependency_overrides[get_db_pool] = get_test_db_pool

    async with LifespanManager(app) as manager:
        yield manager.app


@pytest.fixture
async def app_with_bulk_data(test_db_with_bulk_data, persistent_connection, request):
    """App fixture with pre-loaded bulk test data to avoid notification spam."""
    from app.dependencies import get_db_pool
    from main import make_app

    # Get configuration overrides from request.param, defaulting to empty dict
    config_overrides = getattr(request, "param", {})

    async def get_test_db_pool():
        return test_db_with_bulk_data.pool

    app = make_app(persistent_connection, config_overrides)
    app.dependency_overrides[get_db_pool] = get_test_db_pool

    async with LifespanManager(app) as manager:
        yield manager.app


@pytest.fixture
async def integration_client(app):
    """Create a test client with real database for integration tests."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client


@pytest.fixture
async def integration_client_with_bulk_data(app_with_bulk_data):
    """Create a test client with pre-loaded bulk data (avoids notification spam)."""
    async with AsyncClient(
        transport=ASGITransport(app=app_with_bulk_data), base_url="http://testserver"
    ) as client:
        yield client


@pytest.fixture
async def ws_integration_client(set_env_database_url, app_with_bulk_data):
    """Create a test client with real database for integration tests."""
    async with AsyncClient(
        transport=ASGIWebSocketTransport(app=app_with_bulk_data),
        base_url="http://testserver",
    ) as client:
        yield client


@pytest.fixture
def wind_data_generator():
    """Provide wind data generator."""
    return WindDataGenerator()


@pytest.fixture
def anyio_backend():
    return "asyncio"
