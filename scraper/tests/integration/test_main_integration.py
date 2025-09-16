import asyncio
import os
import pytest
import tempfile
from datetime import datetime, UTC
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from windscraper.config import Config, StationConfig, load_config_from_toml
from windscraper.database import DatabaseHandler
from windscraper.main import StdoutHandler
from windscraper.main import (
    create_output_handler,
    create_status_handler,
    handle_stdout,
    handle_status_stdout,
)
from windscraper.models import WindObs
from windscraper.scraper import Scraper


class TestMainIntegration:
    """Integration tests for main module functionality."""

    @pytest.fixture
    def sample_config(self):
        """Sample configuration for testing."""
        return Config(
            stations=[
                StationConfig(
                    name="TEST_STATION_1",
                    url="https://example.com/api/test1",
                    timeout=10,
                    timezone=UTC,
                ),
                StationConfig(
                    name="TEST_STATION_2",
                    url="https://example.com/api/test2",
                    timeout=15,
                    timezone=UTC,
                ),
            ],
            log_level="DEBUG",
            refresh_rate=30,
            db_url="postgresql://test:test@localhost/test_db",
            output_mode="postgres",
        )

    @pytest.fixture
    def temp_config_file(self, sample_config):
        """Create a temporary config file for testing."""
        config_data = """
[general]
log_level = "DEBUG"
refresh_rate = 30
db_url = "postgresql://test:test@localhost/test_db"
output_mode = "postgres"

[[stations]]
name = "TEST_STATION_1"
url = "https://example.com/api/test1"
timeout = 10
timezone = "UTC"
local_timezone = "America/Toronto"

[[stations]]
name = "TEST_STATION_2"
url = "https://example.com/api/test2"
timeout = 15
timezone = "UTC"
local_timezone = "America/Vancouver"
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write(config_data)
            temp_path = f.name

        yield temp_path
        os.unlink(temp_path)

    @pytest.fixture
    def sample_wind_obs(self):
        """Sample wind observation for testing."""
        return WindObs(
            station="TEST_STATION_1",
            direction=180,
            speed=15.5,
            gust=20.0,
            timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
        )

    def test_load_config_from_toml_file(self, temp_config_file):
        """Test loading configuration from TOML file."""
        config = load_config_from_toml(temp_config_file)

        assert config.log_level == "DEBUG"
        assert config.refresh_rate == 30
        assert config.output_mode == "postgres"
        assert len(config.stations) == 2

        # Check first station
        station1 = config.stations[0]
        assert station1.name == "TEST_STATION_1"
        assert station1.url == "https://example.com/api/test1"
        assert station1.timeout == 10

        # Check second station
        station2 = config.stations[1]
        assert station2.name == "TEST_STATION_2"
        assert station2.url == "https://example.com/api/test2"
        assert station2.timeout == 15

    def test_create_output_handler_postgres_mode(self, sample_config):
        """Test creating output handler for postgres mode."""
        # Mock database handler
        mock_db_handler = MagicMock()

        handler = create_output_handler(sample_config, mock_db_handler)

        # Handler should be a callable function (lambda)
        assert callable(handler)

    def test_create_output_handler_stdout_mode(self, sample_config):
        """Test creating output handler for stdout mode."""
        # Change config to stdout mode
        sample_config.output_mode = "stdout"

        # Create a mock stdout handler
        mock_stdout_handler = MagicMock()

        handler = create_output_handler(sample_config, mock_stdout_handler)

        # Handler should be the stdout function
        assert handler == handle_stdout

    def test_create_status_handler_postgres_mode(self, sample_config):
        """Test creating status handler for postgres mode."""
        # Mock database handler
        mock_db_handler = MagicMock()

        handler = create_status_handler(sample_config, mock_db_handler)

        # Handler should be a callable function (lambda)
        assert callable(handler)

    def test_create_status_handler_stdout_mode(self, sample_config):
        """Test creating status handler for stdout mode."""
        # Change config to stdout mode
        sample_config.output_mode = "stdout"

        handler = create_status_handler(sample_config, None)

        # Handler should be the stdout status function
        assert handler == handle_status_stdout

    @pytest.mark.asyncio
    async def test_handle_stdout_function(self, sample_wind_obs, capsys):
        """Test the stdout output handler."""
        await handle_stdout(sample_wind_obs)

        captured = capsys.readouterr()
        assert "TEST_STATION_1" in captured.out
        assert "180 deg" in captured.out
        assert "15.5-20.0 kts" in captured.out

    @pytest.mark.asyncio
    async def test_handle_status_stdout_function(self, capsys):
        """Test the stdout status handler."""
        # Test with error message
        await handle_status_stdout("TEST_STATION", "error", "Connection failed")

        captured = capsys.readouterr()
        assert "Error: TEST_STATION - error: Connection failed" in captured.out

        # Test without error message
        await handle_status_stdout("TEST_STATION", "success", None)

        captured = capsys.readouterr()
        assert "Status: TEST_STATION - success" in captured.out

    def test_stdout_handler_context_manager(self, sample_config):
        """Test StdoutHandler as context manager."""
        handler = StdoutHandler(sample_config)

        # Test entering context
        result = asyncio.run(handler.__aenter__())
        assert result is handler

        # Test exiting context (should not raise)
        asyncio.run(handler.__aexit__(None, None, None))

    def test_invalid_output_mode_defaults_to_stdout(self, sample_config):
        """Test that invalid output mode defaults to stdout handler."""
        sample_config.output_mode = "invalid"

        # Should default to stdout handler for invalid modes
        handler = create_output_handler(sample_config, None)
        assert handler == handle_stdout

    @pytest.mark.asyncio
    async def test_scraper_creation_with_config(self, sample_config):
        """Test creating scrapers from configuration."""
        # Mock the required dependencies
        mock_requester_builder = MagicMock()
        mock_requester = MagicMock()
        mock_requester_builder.create_requester.return_value = mock_requester

        mock_parser = MagicMock()

        # Set mock handlers before creating scrapers
        mock_output_handler = MagicMock()
        mock_status_handler = MagicMock()

        Scraper.set_output_handler(mock_output_handler)
        Scraper.set_status_handler(mock_status_handler)

        # Create scrapers
        scrapers = []
        for station_config in sample_config.stations:
            scraper = Scraper.create(
                station_config,
                mock_requester_builder.create_requester(station_config),
                mock_parser,
            )
            scrapers.append(scraper)

        assert len(scrapers) == 2
        assert all(isinstance(s, Scraper) for s in scrapers)

        # Verify requester builder was called correctly
        assert mock_requester_builder.create_requester.call_count == 2

    def test_config_with_none_db_url(self):
        """Test configuration with None database URL."""
        config = Config(
            stations=[],
            log_level="INFO",
            refresh_rate=60,
            db_url=None,
            output_mode="stdout",
        )

        assert config.db_url is None
        assert config.output_mode == "stdout"

    def test_config_with_empty_stations(self):
        """Test configuration with empty stations list."""
        config = Config(
            stations=[],
            log_level="INFO",
            refresh_rate=60,
            db_url="postgresql://test:test@localhost/test_db",
            output_mode="postgres",
        )

        assert len(config.stations) == 0
        assert config.log_level == "INFO"
        assert config.refresh_rate == 60

    @pytest.mark.asyncio
    async def test_database_handler_context_manager(self):
        """Test DatabaseHandler as context manager."""
        # Create a config with a dummy URL (won't actually connect)
        config = Config(
            stations=[],
            log_level="INFO",
            refresh_rate=60,
            db_url="postgresql://test:test@localhost/test_db",
            output_mode="postgres",
        )

        handler = DatabaseHandler(config)

        # Test that handler has the expected attributes
        assert hasattr(handler, "config")
        assert hasattr(handler, "lock")
        assert isinstance(handler.lock, asyncio.Lock)

    def test_config_timezone_conversion(self):
        """Test that string timezones are converted to ZoneInfo objects."""

        config = Config(
            stations=[
                StationConfig(
                    name="TEST_STATION",
                    url="https://example.com/api/test",
                    timezone="America/New_York",  # String timezone
                    local_timezone="America/Los_Angeles"
                )
            ],
            log_level="INFO",
            refresh_rate=60,
            db_url=None,
            output_mode="stdout",
        )

        # The StationConfig.__post_init__ should convert string to ZoneInfo
        station = config.stations[0]
        assert isinstance(station.timezone, ZoneInfo)
        assert str(station.timezone) == "America/New_York"
        assert isinstance(station.local_timezone, ZoneInfo)
        assert str(station.local_timezone) == "America/Los_Angeles"
