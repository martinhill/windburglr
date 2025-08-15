import asyncpg
from datetime import datetime, UTC, timedelta


class TestDatabaseManager:
    """Real database manager for integration testing."""

    def __init__(self, database_url):
        self.database_url = database_url
        self.pool = None

    async def setup(self):
        """Initialize database connection pool."""
        if self.database_url:
            try:
                self.pool = await asyncpg.create_pool(self.database_url)
                await self.create_schema()
                return True
            except Exception as e:
                print(f"Failed to connect to database: {e}")
                return False
        return False

    async def cleanup(self):
        """Clean up database connection."""
        if self.pool:
            await self.pool.close()

    async def create_schema(self):
        """Create test database schema."""
        if not self.pool:
            return

        async with self.pool.acquire() as conn:
            # Create extensions
            await conn.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")

            # Create station table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS station (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(10) UNIQUE NOT NULL,
                    timezone_name VARCHAR(50) NOT NULL DEFAULT 'UTC'
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

    async def create_test_data(self, station_name="CYTZ", days=1):
        """Create test data in the database."""
        if not self.pool:
            return []

        async with self.pool.acquire() as conn:
            # Insert station if not exists
            station_id = await conn.fetchval(
                """
                INSERT INTO station (name, timezone_name)
                VALUES ($1, $2)
                ON CONFLICT (name) DO UPDATE SET timezone_name = EXCLUDED.timezone_name
                RETURNING id
                """,
                station_name,
                "America/Toronto",
            )

            # Generate test data
            base_time = datetime.now(UTC)
            data = []

            for i in range(days * 24):
                obs_time = base_time - timedelta(hours=i)
                # Convert to naive datetime for PostgreSQL compatibility
                naive_time = obs_time.replace(tzinfo=None)
                direction = (i * 15) % 360
                speed_kts = 5 + (i % 20)
                gust_kts = speed_kts + 2

                await conn.execute(
                    """
                    INSERT INTO wind_obs (station_id, update_time, direction, speed_kts, gust_kts)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT DO NOTHING
                    """,
                    station_id,
                    naive_time,
                    direction,
                    speed_kts,
                    gust_kts,
                )

                data.append(
                    {
                        "direction": direction,
                        "speed_kts": speed_kts,
                        "gust_kts": gust_kts,
                        "update_time": naive_time,
                    }
                )

            return data

    async def get_station_timezone(self, station_name):
        """Get station timezone from database."""
        if not self.pool:
            return "UTC"

        async with self.pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT timezone_name FROM station WHERE name = $1", station_name
            )
            return result or "UTC"

    async def get_wind_data(self, station_name, start_time, end_time):
        """Get wind data for a station and time range."""
        if not self.pool:
            return []

        async with self.pool.acquire() as conn:
            # Convert to naive datetime for PostgreSQL compatibility
            naive_start = start_time.replace(tzinfo=None)
            naive_end = end_time.replace(tzinfo=None)

            return await conn.fetch(
                """
                SELECT w.direction, w.speed_kts, w.gust_kts, w.update_time
                FROM wind_obs w
                JOIN station s ON w.station_id = s.id
                WHERE s.name = $1 AND w.update_time >= $2 AND w.update_time <= $3
                ORDER BY w.update_time DESC
                """,
                station_name,
                naive_start,
                naive_end,
            )
