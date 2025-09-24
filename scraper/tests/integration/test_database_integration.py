import asyncio
import os
import pytest
import pytest_asyncio
from datetime import datetime, UTC
from contextlib import asynccontextmanager

import asyncpg

from windscraper.config import Config
from windscraper.database import (
    DatabaseHandler,
    handle_postgres,
    handle_status_postgres,
)
from windscraper.models import WindObs, DuplicateObservationError


class TestDatabaseIntegration:
    """Integration tests for database operations."""

    @pytest_asyncio.fixture
    async def db_config(self) -> Config:
        """Database configuration for integration tests."""
        return Config(
            stations=[],
            log_level="DEBUG",
            refresh_rate=30,
            db_url=os.getenv(
                "TEST_DATABASE_URL", "postgresql://windburglr@/windburglr"
            ),
            output_mode="postgres",
        )

    @pytest_asyncio.fixture
    async def db_handler(self, db_config: Config):
        """Database handler instance wrapped in a transaction with rollback for test isolation."""
        class MockPool:

            def __init__(self, conn: asyncpg.Connection):
                self.conn = conn

            @asynccontextmanager
            async def acquire(self):
                yield self.conn

        async with DatabaseHandler(db_config) as handler:
            async with handler.pool.acquire() as conn:
                handler.pool = MockPool(conn)
                transaction = conn.transaction()
                try:
                    await transaction.start()
                    await conn.execute("""
                        INSERT INTO station (name) VALUES ('STATION_1'), ('STATION_2'), ('STATION_3'), ('CYTZ'), ('CYYZ'), ('CYVR')
                        ON CONFLICT (name) DO NOTHING
                    """)

                    yield handler
                finally:
                    await transaction.rollback()

    @pytest_asyncio.fixture
    async def concurrent_db_handler(self, db_config: Config):
        """Concurrent database handler fixture - does not use transaction"""
        async with DatabaseHandler(db_config) as handler:
            async with handler.pool.acquire() as conn:
                try:
                    await conn.execute("""
                        INSERT INTO station (name) VALUES ('STATION_1'), ('STATION_2'), ('STATION_3'), ('CYTZ'), ('CYYZ'), ('CYVR')
                        ON CONFLICT (name) DO NOTHING
                    """)
                    yield handler
                finally:
                    await conn.execute("""
                        DELETE FROM wind_obs;
                        DELETE FROM scraper_status;
                        DELETE FROM station WHERE name IN ('STATION_1', 'STATION_2', 'STATION_3', 'CYTZ', 'CYYZ', 'CYVR')
                    """)

    @pytest.fixture
    def sample_obs_1(self) -> WindObs:
        """Sample wind observation for station 1."""
        return WindObs(
            station="STATION_1",
            direction=180,
            speed=15.5,
            gust=20.0,
            timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
        )

    @pytest.fixture
    def sample_obs_2(self) -> WindObs:
        """Sample wind observation for station 2."""
        return WindObs(
            station="STATION_2",
            direction=90,
            speed=10.0,
            gust=None,
            timestamp=datetime(2024, 1, 1, 12, 5, 0, tzinfo=UTC),
        )

    @pytest.mark.asyncio
    async def test_database_connection(self, db_handler: DatabaseHandler):
        """Test database connection establishment."""
        # Connection should be established via context manager
        assert db_handler.pool is not None

        # Test basic query execution
        async with db_handler.pool.acquire() as conn:
            result = await conn.fetchval("SELECT 1")
            assert result == 1

    @pytest.mark.asyncio
    async def test_insert_single_observation(
        self,
        db_handler: DatabaseHandler,
        sample_obs_1: WindObs,
    ):
        """Test inserting a single wind observation."""

        # Insert observation
        await db_handler.insert_obs(sample_obs_1)

        # Verify insertion
        async with db_handler.pool.acquire() as conn:
            result = await conn.fetchrow(
                """
                SELECT s.name, wo.direction, wo.speed_kts, wo.gust_kts, wo.update_time
                FROM wind_obs wo
                JOIN station s ON wo.station_id = s.id
                WHERE s.name = $1
                """,
                sample_obs_1.station,
            )

        assert result is not None
        assert result["name"] == sample_obs_1.station
        assert result["direction"] == sample_obs_1.direction
        assert result["speed_kts"] == sample_obs_1.speed
        assert result["gust_kts"] == sample_obs_1.gust
        assert result["update_time"] == sample_obs_1.timestamp

    @pytest.mark.asyncio
    async def test_insert_multiple_observations(
        self,
        db_handler: DatabaseHandler,
        sample_obs_1: WindObs,
        sample_obs_2: WindObs,
    ):
        """Test inserting multiple wind observations."""
        # Clean up any existing observations for these stations

        async with db_handler.pool.acquire() as conn:
            await conn.execute(
                """
                DELETE FROM wind_obs
                WHERE station_id IN (
                    SELECT id FROM station WHERE name IN ($1, $2)
                )
                """,
                sample_obs_1.station,
                sample_obs_2.station,
            )

        # Insert both observations
        await db_handler.insert_obs(sample_obs_1)
        await db_handler.insert_obs(sample_obs_2)

        # Verify both insertions

        async with db_handler.pool.acquire() as conn:
            results = await conn.fetch("""
                SELECT s.name, wo.direction, wo.speed_kts, wo.gust_kts
                FROM wind_obs wo
                JOIN station s ON wo.station_id = s.id
                WHERE s.name LIKE 'STATION_%'
                ORDER BY s.name
                """)

        assert len(results) == 2

        # Check first observation
        assert results[0]["name"] == sample_obs_1.station
        assert results[0]["direction"] == sample_obs_1.direction
        assert results[0]["speed_kts"] == sample_obs_1.speed
        assert results[0]["gust_kts"] == sample_obs_1.gust

        # Check second observation
        assert results[1]["name"] == sample_obs_2.station
        assert results[1]["direction"] == sample_obs_2.direction
        assert results[1]["speed_kts"] == sample_obs_2.speed
        assert results[1]["gust_kts"] == sample_obs_2.gust

    @pytest.mark.asyncio
    async def test_duplicate_observation_error(
        self,
        db_handler: DatabaseHandler,
        sample_obs_1: WindObs,
    ):
        """Test handling of duplicate observations."""
        # Clean up any existing observations for this station
        async with db_handler.pool.acquire() as conn:
            await conn.execute(
                """
                DELETE FROM wind_obs
                WHERE station_id = (SELECT id FROM station WHERE name = $1)
                """,
                sample_obs_1.station,
            )

        # Insert first observation
        await db_handler.insert_obs(sample_obs_1)

        # Attempt to insert duplicate (same station and timestamp)
        duplicate_obs = WindObs(
            station=sample_obs_1.station,
            direction=200,  # Different direction
            speed=25.0,  # Different speed
            gust=30.0,  # Different gust
            timestamp=sample_obs_1.timestamp,  # Same timestamp
        )

        # Should raise DuplicateObservationError
        with pytest.raises(DuplicateObservationError) as exc_info:
            await db_handler.insert_obs(duplicate_obs)

        assert sample_obs_1.station in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_concurrent_observation_insertion(
        self, concurrent_db_handler: DatabaseHandler, sample_obs_1: WindObs
    ):
        """Test concurrent insertion of observations."""
        # Clean up any existing observations for this station
        async with concurrent_db_handler.pool.acquire() as conn:
            await conn.execute(
                """
                DELETE FROM wind_obs
                WHERE station_id = (SELECT id FROM station WHERE name = $1)
                """,
                sample_obs_1.station,
            )

        # Create multiple observations with different timestamps
        observations = []
        for i in range(5):
            obs = WindObs(
                station=sample_obs_1.station,
                direction=sample_obs_1.direction,
                speed=sample_obs_1.speed + i,
                gust=sample_obs_1.gust,
                timestamp=datetime(2024, 1, 1, 12, i, 0, tzinfo=UTC),
            )
            observations.append(obs)

        # Insert concurrently
        tasks = [concurrent_db_handler.insert_obs(obs) for obs in observations]
        await asyncio.gather(*tasks)

        # Verify all observations were inserted
        async with concurrent_db_handler.pool.acquire() as conn:
            count = await conn.fetchval(
                """
                SELECT COUNT(*) FROM wind_obs wo
                JOIN station s ON wo.station_id = s.id
                WHERE s.name = $1
                """,
                sample_obs_1.station,
            )

        assert count == 5

    @pytest.mark.asyncio
    async def test_status_update_success(self, db_handler: DatabaseHandler):
        """Test successful status update."""
        station_name = "STATION_1"
        status = "success"
        error_message = None

        # Update status
        await db_handler.update_scraper_status(station_name, status, error_message)

        # Verify station exists (function creates it if not exists)
        async with db_handler.pool.acquire() as conn:
            result = await conn.fetchval(
                """
                SELECT COUNT(*) FROM station WHERE name = $1
                """,
                station_name,
            )

        assert result == 1

    @pytest.mark.asyncio
    async def test_status_update_with_error(self, db_handler: DatabaseHandler):
        """Test status update with error message."""
        station_name = "STATION_2"
        status = "error"
        error_message = "Connection timeout"

        # Update status with error
        await db_handler.update_scraper_status(station_name, status, error_message)

        # Verify station exists
        async with db_handler.pool.acquire() as conn:
            result = await conn.fetchval(
                """
                SELECT COUNT(*) FROM station WHERE name = $1
            """,
                station_name,
            )

        assert result == 1

    @pytest.mark.asyncio
    async def test_observation_with_none_values(self, db_handler: DatabaseHandler):
        """Test inserting observation with None values."""
        obs = WindObs(
            station="STATION_1",
            direction=None,
            speed=5.0,
            gust=None,
            timestamp=datetime(2024, 1, 1, 13, 0, 0, tzinfo=UTC),
        )

        await db_handler.insert_obs(obs)

        # Verify insertion with NULL values

        async with db_handler.pool.acquire() as conn:
            result = await conn.fetchrow(
                """
                SELECT direction, speed_kts, gust_kts
                FROM wind_obs wo
                JOIN station s ON wo.station_id = s.id
                WHERE s.name = $1 AND wo.update_time = $2
                """,
                obs.station,
                obs.timestamp,
            )

        assert result["direction"] is None
        assert result["speed_kts"] == obs.speed
        assert result["gust_kts"] is None

    @pytest.mark.asyncio
    async def test_handle_postgres_function(
        self, db_handler: DatabaseHandler, sample_obs_1: WindObs
    ):
        """Test the handle_postgres function."""
        # Clean up any existing observations for this station
        async with db_handler.pool.acquire() as conn:
            await conn.execute(
                """
                DELETE FROM wind_obs
                WHERE station_id = (SELECT id FROM station WHERE name = $1)
            """,
                sample_obs_1.station,
            )

        # Use the handle_postgres function
        await handle_postgres(sample_obs_1, db_handler)

        # Verify observation was inserted

        async with db_handler.pool.acquire() as conn:
            result = await conn.fetchval(
                """
                SELECT COUNT(*) FROM wind_obs wo
                JOIN station s ON wo.station_id = s.id
                WHERE s.name = $1
                """,
                sample_obs_1.station,
            )

        assert result == 1

    @pytest.mark.asyncio
    async def test_handle_status_postgres_function(self, db_handler: DatabaseHandler):
        """Test the handle_status_postgres function."""
        station_name = "STATION_1"
        status = "running"
        error_message = None

        # Use the handle_status_postgres function
        await handle_status_postgres(station_name, status, error_message, db_handler)

        # Verify station exists
        async with db_handler.pool.acquire() as conn:
            result = await conn.fetchval(
                """
                SELECT COUNT(*) FROM station WHERE name = $1
            """,
                station_name,
            )

        assert result == 1

    @pytest.mark.asyncio
    async def test_duplictate_observations_prevented(
        self, db_handler: DatabaseHandler, sample_obs_1: WindObs
    ):
        """Test that database locks prevent race conditions during insertion."""

        # Create two identical observations
        obs1 = sample_obs_1
        obs2 = WindObs(
            station=sample_obs_1.station,
            direction=sample_obs_1.direction,
            speed=sample_obs_1.speed,
            gust=sample_obs_1.gust,
            timestamp=sample_obs_1.timestamp,
        )

        # Insert first observation
        await db_handler.insert_obs(obs1)

        # Second insertion should fail due to unique constraint
        with pytest.raises(DuplicateObservationError):
            await db_handler.insert_obs(obs2)

    @pytest.mark.asyncio
    async def test_scraper_status_comprehensive_scenarios(
        self, db_handler: DatabaseHandler
    ):
        """Test comprehensive scraper status scenarios with all possible status values."""

        # Test 1: Healthy status
        await db_handler.update_scraper_status("STATION_1", "healthy", None)

        # Test 2: Error status
        await db_handler.update_scraper_status(
            "STATION_2", "error", "Connection timeout"
        )

        # Test 3: Network error status
        await db_handler.update_scraper_status(
            "STATION_3", "network_error", "DNS resolution failed"
        )

        # Test 4: Parse error status
        await db_handler.update_scraper_status(
            "STATION_1", "parse_error", "Invalid JSON response"
        )

        # Test 5: Stale data status
        await db_handler.update_scraper_status(
            "STATION_2", "stale_data", "Data older than 1 hour"
        )

        # Verify all status updates

        async with db_handler.pool.acquire() as conn:
            results = await conn.fetch("""
                SELECT s.name, ss.status, ss.error_message, ss.retry_count
                FROM station s
                LEFT JOIN scraper_status ss ON s.id = ss.station_id
                WHERE s.name LIKE 'STATION_%'
                ORDER BY s.name
            """)

        assert len(results) == 3

        # Check STATION_1: should be parse_error (latest update)
        assert results[0]["name"] == "STATION_1"
        assert results[0]["status"] == "parse_error"
        assert results[0]["error_message"] == "Invalid JSON response"
        assert results[0]["retry_count"] == 1  # First error after healthy status

        # Check STATION_2: should be stale_data (latest update)
        assert results[1]["name"] == "STATION_2"
        assert results[1]["status"] == "stale_data"
        assert results[1]["error_message"] == "Data older than 1 hour"
        assert results[1]["retry_count"] == 0  # First error, starts at 0

        # Check STATION_3: should be network_error
        assert results[2]["name"] == "STATION_3"
        assert results[2]["status"] == "network_error"
        assert results[2]["error_message"] == "DNS resolution failed"
        assert results[2]["retry_count"] == 0

    @pytest.mark.asyncio
    async def test_get_scraper_status_function(self, db_handler: DatabaseHandler):
        """Test the get_scraper_status database function."""

        # Set up different status scenarios using existing stations
        await db_handler.update_scraper_status("CYTZ", "healthy", None)
        await db_handler.update_scraper_status("CYYZ", "error", "Connection failed")
        await db_handler.update_scraper_status("CYVR", "network_error", "Timeout")

        # Call get_scraper_status function
        async with db_handler.pool.acquire() as conn:
            status_results = await conn.fetch(
                "SELECT * FROM get_scraper_status()"
            )

        # Should return all stations (3 existing + 3 test stations = 6 total)
        assert len(status_results) == 6

        # Find results by station name
        cytz_result = next(r for r in status_results if r["station_name"] == "CYTZ")
        cyyz_result = next(r for r in status_results if r["station_name"] == "CYYZ")
        cyvr_result = next(r for r in status_results if r["station_name"] == "CYVR")

        # Verify CYTZ (healthy)
        assert cytz_result["status"] == "healthy"
        assert cytz_result["error_message"] is None
        assert cytz_result["retry_count"] == 0
        assert cytz_result["last_success"] is not None
        assert cytz_result["time_since_last_attempt"] is not None
        assert cytz_result["time_since_last_success"] is not None

        # Verify CYYZ (error)
        assert cyyz_result["status"] == "error"
        assert cyyz_result["error_message"] == "Connection failed"
        assert cyyz_result["retry_count"] == 0
        assert cyyz_result["last_success"] is None  # No successful attempts
        assert cyyz_result["time_since_last_attempt"] is not None
        assert cyyz_result["time_since_last_success"] is None

        # Verify CYVR (network_error)
        assert cyvr_result["status"] == "network_error"
        assert cyvr_result["error_message"] == "Timeout"
        assert cyvr_result["retry_count"] == 0
        assert cyvr_result["last_success"] is None
        assert cyvr_result["time_since_last_attempt"] is not None
        assert cyvr_result["time_since_last_success"] is None

    @pytest.mark.asyncio
    async def test_get_scraper_health_function_all_healthy(
        self, db_handler: DatabaseHandler
    ):
        """Test get_scraper_health function when all stations are healthy."""
        # Set all existing stations to healthy
        await db_handler.update_scraper_status("CYTZ", "healthy", None)
        await db_handler.update_scraper_status("CYYZ", "healthy", None)
        await db_handler.update_scraper_status("CYVR", "healthy", None)

        # Call get_scraper_health function
        async with db_handler.pool.acquire() as conn:
            health_result = await conn.fetchrow("SELECT * FROM get_scraper_health()")

        assert health_result["total_stations"] == 6  # 3 existing + 3 test stations
        assert health_result["healthy_stations"] == 3  # Only the 3 we set to healthy
        assert health_result["error_stations"] == 0
        assert health_result["stale_stations"] == 0
        assert (
            health_result["overall_status"] == "unknown"
        )  # Not all stations are healthy

    @pytest.mark.asyncio
    async def test_get_scraper_health_function_with_errors(
        self, db_handler: DatabaseHandler
    ):
        """Test get_scraper_health function with various error conditions."""
        # Create test stations

        # Set up mixed status: 1 healthy, 1 error, 1 network_error
        await db_handler.update_scraper_status("STATION_1", "healthy", None)
        await db_handler.update_scraper_status("STATION_2", "error", "Parse failed")
        await db_handler.update_scraper_status(
            "STATION_3", "network_error", "Connection timeout"
        )

        # Call get_scraper_health function
        async with db_handler.pool.acquire() as conn:
            health_result = await conn.fetchrow("SELECT * FROM get_scraper_health()")

        assert health_result["total_stations"] == 6  # 3 existing + 3 test stations
        assert health_result["healthy_stations"] == 1  # STATION_1
        assert (
            health_result["error_stations"] == 2
        )  # STATION_2 error + STATION_3 network_error
        assert health_result["stale_stations"] == 0
        assert health_result["overall_status"] == "error"  # error takes precedence

    @pytest.mark.asyncio
    async def test_get_scraper_health_function_with_stale_data(
        self, db_handler: DatabaseHandler
    ):
        """Test get_scraper_health function with stale data."""
        # Set up: 2 healthy, 1 stale_data
        await db_handler.update_scraper_status("STATION_1", "healthy", None)
        await db_handler.update_scraper_status("STATION_2", "healthy", None)
        await db_handler.update_scraper_status("STATION_3", "stale_data", "Old data")

        # Call get_scraper_health function
        async with db_handler.pool.acquire() as conn:
            health_result = await conn.fetchrow("SELECT * FROM get_scraper_health()")

        assert health_result["total_stations"] == 6  # 3 existing + 3 test stations
        assert health_result["healthy_stations"] == 2  # STATION_1 + STATION_2
        assert health_result["error_stations"] == 0
        assert health_result["stale_stations"] == 1  # STATION_3 stale_data
        assert health_result["overall_status"] == "warning"  # stale_data causes warning

    @pytest.mark.asyncio
    async def test_get_scraper_health_function_stale_healthy_station(
        self, db_handler: DatabaseHandler
    ):
        """Test get_scraper_health function when healthy station becomes stale."""

        # First set station to healthy
        await db_handler.update_scraper_status("STATION_1", "healthy", None)

        # Manually set last_attempt to be more than 5 minutes ago to simulate staleness
        async with db_handler.pool.acquire() as conn:
            await conn.execute("""
                UPDATE scraper_status
                SET last_attempt = NOW() - INTERVAL '10 minutes'
                WHERE station_id = (SELECT id FROM station WHERE name = 'STATION_1')
            """)

        # Call get_scraper_health function
        async with db_handler.pool.acquire() as conn:
            health_result = await conn.fetchrow("SELECT * FROM get_scraper_health()")

        # The healthy station that hasn't been updated in 5+ minutes should be counted as error
        assert health_result["total_stations"] == 6  # 3 existing + 3 test stations
        assert health_result["healthy_stations"] == 0
        assert health_result["error_stations"] == 1  # STATION_1 is now stale (error)
        assert (
            health_result["stale_stations"] == 0
        )  # No stations have stale_data status
        assert health_result["overall_status"] == "error"

    @pytest.mark.asyncio
    async def test_retry_count_increment_on_errors(self, db_handler: DatabaseHandler):
        """Test that retry_count increments properly on consecutive errors."""
        station_name = "STATION_1"

        # Clear any existing scraper status for this station
        async with db_handler.pool.acquire() as conn:
            await conn.execute(
                """
                DELETE FROM scraper_status
                WHERE station_id = (SELECT id FROM station WHERE name = $1)
                """,
                station_name,
            )

        # First error
        await db_handler.update_scraper_status(station_name, "error", "First failure")
        async with db_handler.pool.acquire() as conn:
            result1 = await conn.fetchrow(
                """
                SELECT retry_count FROM scraper_status
                WHERE station_id = (SELECT id FROM station WHERE name = $1)
                """,
                station_name,
            )
        assert result1["retry_count"] == 0  # First error, starts at 0

        # Second error - should increment
        await db_handler.update_scraper_status(station_name, "error", "Second failure")
        async with db_handler.pool.acquire() as conn:
            result2 = await conn.fetchrow(
                """
                SELECT retry_count FROM scraper_status
                WHERE station_id = (SELECT id FROM station WHERE name = $1)
                """,
                station_name,
            )
        assert result2["retry_count"] == 1

        # Third error - should increment further
        await db_handler.update_scraper_status(station_name, "error", "Third failure")
        async with db_handler.pool.acquire() as conn:
            result3 = await conn.fetchrow(
                """
                SELECT retry_count FROM scraper_status
                WHERE station_id = (SELECT id FROM station WHERE name = $1)
                """,
                station_name,
            )
        assert result3["retry_count"] == 2

        # Success - should reset to 0
        await db_handler.update_scraper_status(station_name, "healthy", None)
        async with db_handler.pool.acquire() as conn:
            result4 = await conn.fetchrow(
                """
                SELECT retry_count FROM scraper_status
                WHERE station_id = (SELECT id FROM station WHERE name = $1)
                """,
                station_name,
            )
        assert result4["retry_count"] == 0

    @pytest.mark.asyncio
    async def test_scraper_status_last_success_tracking(
        self, db_handler: DatabaseHandler
    ):
        """Test that last_success is properly tracked."""
        station_name = "STATION_1"

        # Initial error - no last_success
        await db_handler.update_scraper_status(station_name, "error", "Initial failure")
        async with db_handler.pool.acquire() as conn:
            result1 = await conn.fetchrow(
                """
                SELECT last_success FROM scraper_status
                WHERE station_id = (SELECT id FROM station WHERE name = $1)
                """,
                station_name,
            )
        assert result1["last_success"] is None

        # First success - should set last_success
        await db_handler.update_scraper_status(station_name, "healthy", None)
        async with db_handler.pool.acquire() as conn:
            result2 = await conn.fetchrow(
                """
                SELECT last_success FROM scraper_status
                WHERE station_id = (SELECT id FROM station WHERE name = $1)
                """,
                station_name,
            )
        assert result2["last_success"] is not None

        # Subsequent error - should not change last_success
        await db_handler.update_scraper_status(station_name, "error", "Later failure")
        async with db_handler.pool.acquire() as conn:
            result3 = await conn.fetchrow(
                """
                SELECT last_success FROM scraper_status
                WHERE station_id = (SELECT id FROM station WHERE name = $1)
                """,
                station_name,
            )
        assert (
            result3["last_success"] == result2["last_success"]
        )  # Should remain the same

        # Another success - should update last_success
        await db_handler.update_scraper_status(station_name, "healthy", None)

        async with db_handler.pool.acquire() as conn:
            result4 = await conn.fetchrow(
                """
                SELECT last_success FROM scraper_status
                WHERE station_id = (SELECT id FROM station WHERE name = $1)
                """,
                station_name,
            )
        assert result4["last_success"] != result2["last_success"]  # Should be updated
