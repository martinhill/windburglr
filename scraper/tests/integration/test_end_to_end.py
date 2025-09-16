import asyncio
import os
import tempfile
import pytest
import pytest_asyncio
from datetime import datetime, UTC

from windscraper.config import Config, StationConfig, load_config_from_toml
from windscraper.database import DatabaseHandler
from windscraper.main import create_output_handler, create_status_handler
from windscraper.models import WindObs


class TestEndToEndIntegration:
    """End-to-end integration tests combining database and main modules."""

    @pytest_asyncio.fixture
    async def db_config(self):
        """Database configuration for end-to-end tests."""
        return Config(
            stations=[
                StationConfig(
                    name="E2E_STN_1",
                    url="https://example.com/api/e2e1",
                    timeout=10,
                    timezone=UTC,
                ),
                StationConfig(
                    name="E2E_STN_2",
                    url="https://example.com/api/e2e2",
                    timeout=15,
                    timezone=UTC,
                ),
            ],
            log_level="DEBUG",
            refresh_rate=30,
            db_url=os.getenv(
                "TEST_DATABASE_URL", "postgresql://windburglr@/windburglr"
            ),
            output_mode="postgres",
        )

    @pytest_asyncio.fixture
    async def temp_config_file(self, db_config):
        """Create a temporary config file for end-to-end testing."""
        config_data = """
[general]
log_level = "DEBUG"
refresh_rate = 30
db_url = "postgresql://windburglr@/windburglr"
output_mode = "postgres"

[[stations]]
name = "E2E_STN_1"
url = "https://example.com/api/e2e1"
timeout = 10
timezone = "UTC"
local_timezone = "America/Vancouver"

[[stations]]
name = "E2E_STN_2"
url = "https://example.com/api/e2e2"
timeout = 15
timezone = "UTC"
local_timezone = "America/Vancouver"
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write(config_data)
            temp_path = f.name

        yield temp_path
        os.unlink(temp_path)

    @pytest_asyncio.fixture
    async def setup_e2e_db(self, db_config):
        """Set up database schema for end-to-end tests."""
        async with DatabaseHandler(db_config) as db_handler:
            transaction = db_handler.conn.transaction()
            try:
                await transaction.start()
                # Insert test stations
                await db_handler.conn.execute("""
                    INSERT INTO station (name) VALUES ('E2E_STN_1'), ('E2E_STN_2')
                    ON CONFLICT (name) DO NOTHING
                """)

                yield db_handler
            finally:
                await transaction.rollback()
                # Special case for end-to-end tests, needs manual cleanup
                await db_handler.conn.execute("DELETE FROM station WHERE name IN ('E2E_STN_1', 'E2E_STN_2')")

    @pytest.mark.asyncio
    async def test_full_config_loading_and_validation(self, temp_config_file):
        """Test loading and validating a complete configuration."""
        config = load_config_from_toml(temp_config_file)

        assert config.log_level == "DEBUG"
        assert config.refresh_rate == 30
        assert config.output_mode == "postgres"
        assert len(config.stations) == 2

        # Validate station configurations
        station1 = config.stations[0]
        assert station1.name == "E2E_STN_1"
        assert station1.url == "https://example.com/api/e2e1"
        assert station1.timeout == 10

        station2 = config.stations[1]
        assert station2.name == "E2E_STN_2"
        assert station2.url == "https://example.com/api/e2e2"
        assert station2.timeout == 15

    @pytest.mark.asyncio
    async def test_database_and_main_module_integration(self, db_config, setup_e2e_db):
        """Test integration between database and main modules."""
        db_handler = setup_e2e_db

        # Create output and status handlers
        output_handler = create_output_handler(db_config, db_handler)
        status_handler = create_status_handler(db_config, db_handler)

        # Verify handlers are callable
        assert callable(output_handler)
        assert callable(status_handler)

        # Test output handler with sample observation
        sample_obs = WindObs(
            station="E2E_STN_1",
            direction=180,
            speed=15.5,
            gust=20.0,
            timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
        )

        # This should insert the observation into the database
        await output_handler(sample_obs)

        # Verify the observation was inserted
        result = await db_handler.conn.fetchrow(
            """
            SELECT s.name, wo.direction, wo.speed_kts, wo.gust_kts
            FROM wind_obs wo
            JOIN station s ON wo.station_id = s.id
            WHERE s.name = $1
        """,
            sample_obs.station,
        )

        assert result is not None
        assert result["name"] == sample_obs.station
        assert result["direction"] == sample_obs.direction
        assert result["speed_kts"] == sample_obs.speed
        assert result["gust_kts"] == sample_obs.gust

    @pytest.mark.asyncio
    async def test_multiple_stations_data_flow(self, db_config, setup_e2e_db):
        """Test data flow for multiple stations."""
        db_handler = setup_e2e_db
        output_handler = create_output_handler(db_config, db_handler)

        # Create observations for both stations
        observations = [
            WindObs(
                station="E2E_STN_1",
                direction=180,
                speed=15.5,
                gust=20.0,
                timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
            ),
            WindObs(
                station="E2E_STN_2",
                direction=90,
                speed=10.0,
                gust=None,
                timestamp=datetime(2024, 1, 1, 12, 5, 0, tzinfo=UTC),
            ),
        ]

        # Insert all observations
        for obs in observations:
            await output_handler(obs)

        # Verify both observations were inserted
        results = await db_handler.conn.fetch("""
            SELECT s.name, wo.direction, wo.speed_kts, wo.gust_kts
            FROM wind_obs wo
            JOIN station s ON wo.station_id = s.id
            WHERE s.name LIKE 'E2E_STN_%'
            ORDER BY s.name
        """)

        assert len(results) == 2

        # Check first station
        assert results[0]["name"] == "E2E_STN_1"
        assert results[0]["direction"] == 180
        assert results[0]["speed_kts"] == 15.5
        assert results[0]["gust_kts"] == 20.0

        # Check second station
        assert results[1]["name"] == "E2E_STN_2"
        assert results[1]["direction"] == 90
        assert results[1]["speed_kts"] == 10.0
        assert results[1]["gust_kts"] is None

    @pytest.mark.asyncio
    async def test_status_updates_integration(self, db_config, setup_e2e_db):
        """Test status update integration."""
        db_handler = setup_e2e_db
        status_handler = create_status_handler(db_config, db_handler)

        # Update status for a station
        await status_handler("E2E_STN_1", "success", None)

        # Verify station exists (created by status update function)
        result = await db_handler.conn.fetchval(
            """
            SELECT COUNT(*) FROM station WHERE name = $1
        """,
            "E2E_STN_1",
        )

        assert result == 1

    @pytest.mark.asyncio
    async def test_error_handling_in_output_flow(self, db_config, setup_e2e_db):
        """Test error handling in the output flow."""
        db_handler = setup_e2e_db
        output_handler = create_output_handler(db_config, db_handler)

        # Test with observation that has None values
        obs_with_nulls = WindObs(
            station="E2E_STN_1",
            direction=None,
            speed=5.0,
            gust=None,
            timestamp=datetime(2024, 1, 1, 13, 0, 0, tzinfo=UTC),
        )

        # This should handle None values correctly
        await output_handler(obs_with_nulls)

        # Verify insertion with NULL values
        result = await db_handler.conn.fetchrow(
            """
            SELECT direction, speed_kts, gust_kts
            FROM wind_obs wo
            JOIN station s ON wo.station_id = s.id
            WHERE s.name = $1 AND wo.update_time = $2
        """,
            obs_with_nulls.station,
            obs_with_nulls.timestamp,
        )

        assert result["direction"] is None
        assert result["speed_kts"] == obs_with_nulls.speed
        assert result["gust_kts"] is None

    @pytest.mark.asyncio
    async def test_concurrent_operations_simulation(self, db_config, setup_e2e_db):
        """Test concurrent operations simulation."""
        db_handler = setup_e2e_db
        output_handler = create_output_handler(db_config, db_handler)

        # Create multiple observations for concurrent insertion
        observations = []
        for i in range(5):
            obs = WindObs(
                station="E2E_STN_1",
                direction=180 + i * 10,
                speed=10.0 + i,
                gust=15.0 + i,
                timestamp=datetime(2024, 1, 1, 12, i, 0, tzinfo=UTC),
            )
            observations.append(obs)

        # Insert concurrently
        tasks = [output_handler(obs) for obs in observations]
        await asyncio.gather(*tasks)

        # Verify all observations were inserted
        count = await db_handler.conn.fetchval(
            """
            SELECT COUNT(*) FROM wind_obs wo
            JOIN station s ON wo.station_id = s.id
            WHERE s.name = $1
        """,
            "E2E_STN_1",
        )

        assert count == 5
