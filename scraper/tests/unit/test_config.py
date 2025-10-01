import os
import tempfile
from datetime import UTC

import pytest
from zoneinfo import ZoneInfo

from windscraper.config import Config, StationConfig, load_config_from_toml


class TestStationConfig:
    """Test cases for StationConfig dataclass."""

    def test_station_config_creation(self, sample_station_config: StationConfig):
        """Test creating a StationConfig instance."""
        assert sample_station_config.name == "TEST_STATION"
        assert sample_station_config.url == "https://example.com/api/test"
        assert sample_station_config.timeout == 10
        assert sample_station_config.headers == {"User-Agent": "test-agent"}
        assert sample_station_config.timezone == UTC
        assert sample_station_config.local_timezone == ZoneInfo("America/Toronto")

    def test_station_config_defaults(self):
        """Test StationConfig with default values."""
        config = StationConfig(
            name="DEFAULT_STATION", url="https://example.com/api/default"
        )

        assert config.name == "DEFAULT_STATION"
        assert config.url == "https://example.com/api/default"
        assert config.timeout == 15  # default value
        assert config.headers is None  # default value
        assert config.timezone == UTC  # default value
        assert config.parser == "json"  # default value
        assert config.stale_data_timeout == 300  # default value

    def test_station_config_timezone_string_conversion(self):
        """Test that timezone string is converted to ZoneInfo."""
        config = StationConfig(
            name="TZ_STATION",
            url="https://example.com/api/tz",
            timezone=ZoneInfo("America/New_York"),
        )

        assert isinstance(config.timezone, ZoneInfo)
        assert str(config.timezone) == "America/New_York"

    def test_station_config_timezone_object_passthrough(self):
        """Test that ZoneInfo objects are passed through unchanged."""
        tz = ZoneInfo("Europe/London")
        config = StationConfig(
            name="TZ_OBJ_STATION", url="https://example.com/api/tz_obj", timezone=tz
        )

        assert config.timezone is tz
        assert config.timezone == ZoneInfo("Europe/London")

    def test_station_config_equality(self):
        """Test equality comparison of StationConfig instances."""
        config1 = StationConfig(
            name="STATION_A",
            url="https://example.com/a",
            timeout=10,
            headers={"User-Agent": "test"},
        )
        config2 = StationConfig(
            name="STATION_A",
            url="https://example.com/a",
            timeout=10,
            headers={"User-Agent": "test"},
        )
        config3 = StationConfig(
            name="STATION_B", url="https://example.com/b", timeout=10
        )

        assert config1 == config2
        assert config1 != config3

    def test_station_config_with_all_fields(self):
        """Test StationConfig with all optional fields set."""
        headers = {"Authorization": "Bearer token", "User-Agent": "custom-agent"}
        tz = ZoneInfo("Pacific/Auckland")
        local_tz = ZoneInfo("America/Vancouver")

        config = StationConfig(
            name="FULL_STATION",
            url="https://api.example.com/weather",
            timeout=30,
            headers=headers,
            parser="xml",
            direction_path="wind/dir",
            speed_path="wind/speed",
            gust_path="wind/gust",
            timestamp_path="timestamp",
            timestamp_format="%Y-%m-%dT%H:%M:%SZ",
            timezone=tz,
            local_timezone=local_tz,
        )

        assert config.name == "FULL_STATION"
        assert config.url == "https://api.example.com/weather"
        assert config.timeout == 30
        assert config.headers == headers
        assert config.parser == "xml"
        assert config.direction_path == "wind/dir"
        assert config.speed_path == "wind/speed"
        assert config.gust_path == "wind/gust"
        assert config.timestamp_path == "timestamp"
        assert config.timestamp_format == "%Y-%m-%dT%H:%M:%SZ"
        assert config.timezone == tz
        assert config.local_timezone == local_tz


class TestConfig:
    """Test cases for Config dataclass."""

    def test_config_creation(self, sample_config: Config):
        """Test creating a Config instance."""
        assert sample_config.log_level == "DEBUG"
        assert sample_config.refresh_rate == 30
        assert sample_config.db_url == "postgresql://test:test@localhost/test_db"
        assert sample_config.output_mode == "postgres"
        assert len(sample_config.stations) == 1
        assert sample_config.stations[0].name == "TEST_STATION"

    def test_config_defaults(self):
        """Test Config with default values."""
        config = Config()

        assert config.log_level == "INFO"  # default value
        assert config.refresh_rate == 60  # default value
        assert config.db_url is None  # default value
        assert config.output_mode == "postgres"  # default value
        assert config.stations == []  # default value

    def test_config_with_multiple_stations(self):
        """Test Config with multiple stations."""
        station1 = StationConfig(name="STATION_1", url="https://api1.example.com")
        station2 = StationConfig(name="STATION_2", url="https://api2.example.com")
        station3 = StationConfig(name="STATION_3", url="https://api3.example.com")

        config = Config(
            stations=[station1, station2, station3],
            log_level="WARNING",
            refresh_rate=120,
            db_url="postgresql://user:pass@host/db",
            output_mode="stdout",
        )

        assert len(config.stations) == 3
        assert config.stations[0].name == "STATION_1"
        assert config.stations[1].name == "STATION_2"
        assert config.stations[2].name == "STATION_3"
        assert config.log_level == "WARNING"
        assert config.refresh_rate == 120
        assert config.db_url == "postgresql://user:pass@host/db"
        assert config.output_mode == "stdout"


class TestLoadConfigFromToml:
    """Test cases for load_config_from_toml function."""

    def test_load_config_from_toml_basic(self, temp_config_file: str):
        """Test loading basic config from TOML file."""
        config = load_config_from_toml(temp_config_file)

        assert config.log_level == "DEBUG"
        assert config.refresh_rate == 30
        assert config.db_url == "postgresql://test:test@localhost/test_db"
        assert config.output_mode == "postgres"
        assert len(config.stations) == 1

        station = config.stations[0]
        assert station.name == "TEST_STATION"
        assert station.url == "https://example.com/api/test"
        assert station.timeout == 10
        assert station.headers == {"User-Agent": "test-agent"}
        assert station.timezone == ZoneInfo("UTC")
        assert station.local_timezone == ZoneInfo("America/Toronto")

    def test_load_config_from_toml_minimal(self):
        """Test loading minimal config from TOML file."""
        config_data = """
[general]
log_level = "INFO"
refresh_rate = 60

[[stations]]
name = "MINIMAL_STATION"
local_timezone = "America/Toronto"
url = "https://minimal.example.com"
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write(config_data)
            temp_path = f.name

        try:
            config = load_config_from_toml(temp_path)

            assert config.log_level == "INFO"
            assert config.refresh_rate == 60
            assert config.db_url is None
            assert config.output_mode == "postgres"
            assert len(config.stations) == 1

            station = config.stations[0]
            assert station.name == "MINIMAL_STATION"
            assert station.url == "https://minimal.example.com"
            assert station.timeout == 15  # default
            assert station.headers is None  # default
            assert station.timezone == UTC  # default
            assert station.local_timezone == ZoneInfo("America/Toronto")
        finally:
            os.unlink(temp_path)

    def test_load_config_from_toml_multiple_stations(self):
        """Test loading config with multiple stations."""
        config_data = """
[general]
log_level = "ERROR"
refresh_rate = 300
db_url = "postgresql://prod:pass@prod-db/prod_db"
output_mode = "stdout"

[[stations]]
name = "STATION_1"
local_timezone = "America/Montreal"
url = "https://api1.example.com"
timeout = 20
[stations.headers]
Authorization = "Bearer token1"

[[stations]]
name = "STATION_2"
local_timezone = "America/Toronto"
url = "https://api2.example.com"
timeout = 25
timezone = "America/New_York"
[stations.headers]
Authorization = "Bearer token2"

[[stations]]
name = "STATION_3"
local_timezone = "America/Vancouver"
url = "https://api3.example.com"
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write(config_data)
            temp_path = f.name

        try:
            config = load_config_from_toml(temp_path)

            assert config.log_level == "ERROR"
            assert config.refresh_rate == 300
            assert config.db_url == "postgresql://prod:pass@prod-db/prod_db"
            assert config.output_mode == "stdout"
            assert len(config.stations) == 3

            # Check first station
            station1 = config.stations[0]
            assert station1.name == "STATION_1"
            assert station1.url == "https://api1.example.com"
            assert station1.timeout == 20
            assert station1.headers == {"Authorization": "Bearer token1"}
            assert station1.timezone == UTC  # default
            assert station1.local_timezone == ZoneInfo("America/Montreal")

            # Check second station
            station2 = config.stations[1]
            assert station2.name == "STATION_2"
            assert station2.url == "https://api2.example.com"
            assert station2.timeout == 25
            assert station2.headers == {"Authorization": "Bearer token2"}
            assert station2.timezone == ZoneInfo("America/New_York")
            assert station2.local_timezone == ZoneInfo("America/Toronto")

            # Check third station
            station3 = config.stations[2]
            assert station3.name == "STATION_3"
            assert station3.url == "https://api3.example.com"
            assert station3.timeout == 15  # default
            assert station3.headers is None  # default
            assert station3.timezone == UTC  # default
            assert station3.local_timezone == ZoneInfo("America/Vancouver")

        finally:
            os.unlink(temp_path)

    def test_load_config_from_toml_missing_general_section(self):
        """Test loading config with missing general section."""
        config_data = """
[[stations]]
name = "STATION"
local_timezone = "America/Toronto"
url = "https://example.com"
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write(config_data)
            temp_path = f.name

        try:
            config = load_config_from_toml(temp_path)

            # Should use all defaults
            assert config.log_level == "INFO"
            assert config.refresh_rate == 60
            assert config.db_url is None
            assert config.output_mode == "postgres"
            assert len(config.stations) == 1
        finally:
            os.unlink(temp_path)

    def test_load_config_from_toml_missing_stations_section(self):
        """Test loading config with missing stations section."""
        config_data = """
[general]
log_level = "DEBUG"
refresh_rate = 45
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write(config_data)
            temp_path = f.name

        try:
            config = load_config_from_toml(temp_path)

            assert config.log_level == "DEBUG"
            assert config.refresh_rate == 45
            assert config.stations == []  # empty list
        finally:
            os.unlink(temp_path)

    def test_load_config_from_toml_file_not_found(self):
        """Test loading config from non-existent file."""
        with pytest.raises(FileNotFoundError):
            load_config_from_toml("/non/existent/file.toml")

    def test_load_config_from_toml_invalid_toml(self):
        """Test loading invalid TOML file."""
        invalid_toml = """
[general
log_level = "DEBUG"  # Missing closing bracket
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write(invalid_toml)
            temp_path = f.name

        try:
            with pytest.raises(Exception):  # TOML parsing error
                load_config_from_toml(temp_path)
        finally:
            os.unlink(temp_path)
