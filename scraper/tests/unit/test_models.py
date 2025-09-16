import pytest
from datetime import datetime, UTC

from windscraper.models import (
    WindObs,
    WindburglrError,
    MaxRetriesExceededError,
    StaleWindObservationError,
    DuplicateObservationError,
)


class TestWindObs:
    """Test cases for WindObs dataclass."""

    def test_wind_obs_creation(self, sample_wind_obs: WindObs):
        """Test creating a WindObs instance."""
        assert sample_wind_obs.station == "TEST_STATION"
        assert sample_wind_obs.direction == 180
        assert sample_wind_obs.speed == 15.5
        assert sample_wind_obs.gust == 20.0
        assert isinstance(sample_wind_obs.timestamp, datetime)

    def test_wind_obs_string_representation(self, sample_wind_obs: WindObs):
        """Test string representation of WindObs."""
        expected = "TEST_STATION at 2024-01-01 12:00:00+00:00: 180 deg, 15.5-20.0 kts"
        assert str(sample_wind_obs) == expected

    def test_wind_obs_string_representation_none_direction(self):
        """Test string representation when direction is None."""
        obs = WindObs(
            station="TEST_STATION",
            direction=None,
            speed=10.0,
            gust=15.0,
            timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
        )
        expected = (
            "TEST_STATION at 2024-01-01 12:00:00+00:00: unknown deg, 10.0-15.0 kts"
        )
        assert str(obs) == expected

    def test_wind_obs_string_representation_no_gust(self):
        """Test string representation when gust is None."""
        obs = WindObs(
            station="TEST_STATION",
            direction=90,
            speed=10.0,
            gust=None,
            timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
        )
        expected = "TEST_STATION at 2024-01-01 12:00:00+00:00: 90 deg, 10.0 kts"
        assert str(obs) == expected

    def test_wind_obs_equality(self):
        """Test equality comparison of WindObs instances."""
        obs1 = WindObs(
            station="STATION_A",
            direction=180,
            speed=15.0,
            gust=20.0,
            timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
        )
        obs2 = WindObs(
            station="STATION_A",
            direction=180,
            speed=15.0,
            gust=20.0,
            timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
        )
        obs3 = WindObs(
            station="STATION_B",
            direction=180,
            speed=15.0,
            gust=20.0,
            timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
        )

        assert obs1 == obs2
        assert obs1 != obs3

    def test_wind_obs_with_none_values(self):
        """Test WindObs with None values for direction and gust."""
        obs = WindObs(
            station="TEST_STATION",
            direction=None,
            speed=5.0,
            gust=None,
            timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
        )

        assert obs.direction is None
        assert obs.speed == 5.0
        assert obs.gust is None
        assert obs.station == "TEST_STATION"

        # Test string representation with None values
        expected = "TEST_STATION at 2024-01-01 12:00:00+00:00: unknown deg, 5.0 kts"
        assert str(obs) == expected


class TestWindburglrError:
    """Test cases for WindburglrError exception."""

    def test_windburglr_error_creation(self):
        """Test creating a WindburglrError."""
        error = WindburglrError("Test error message")
        assert str(error) == "Test error message"
        assert isinstance(error, Exception)

    def test_windburglr_error_inheritance(self):
        """Test that WindburglrError inherits from Exception."""
        error = WindburglrError("Test error")
        assert isinstance(error, Exception)


class TestMaxRetriesExceededError:
    """Test cases for MaxRetriesExceededError exception."""

    def test_max_retries_exceeded_creation(self):
        """Test creating a MaxRetriesExceededError."""
        error = MaxRetriesExceededError("Max retries exceeded")
        assert str(error) == "Max retries exceeded"
        assert isinstance(error, WindburglrError)
        assert isinstance(error, Exception)

    def test_max_retries_exceeded_with_cause(self):
        """Test MaxRetriesExceededError with a cause."""
        cause = ValueError("Original error")
        error = MaxRetriesExceededError("Max retries exceeded")
        error.__cause__ = cause

        assert error.__cause__ == cause


class TestStaleWindObservationError:
    """Test cases for StaleWindObservationError exception."""

    def test_stale_observation_creation(self):
        """Test creating a StaleWindObservationError."""
        error = StaleWindObservationError("Stale observation")
        assert str(error) == "Stale observation"
        assert isinstance(error, WindburglrError)
        assert isinstance(error, Exception)


class TestDuplicateObservationError:
    """Test cases for DuplicateObservationError exception."""

    def test_duplicate_observation_creation(self):
        """Test creating a DuplicateObservationError."""
        error = DuplicateObservationError("Duplicate observation")
        assert str(error) == "Duplicate observation"
        assert isinstance(error, WindburglrError)
        assert isinstance(error, Exception)

    def test_duplicate_observation_with_wind_obs(self, sample_wind_obs: WindObs):
        """Test DuplicateObservationError with WindObs context."""
        error = DuplicateObservationError(f"Duplicate: {sample_wind_obs}")
        assert "TEST_STATION" in str(error)
        assert "180" in str(error)
        assert "15.5" in str(error)


class TestExceptionHierarchy:
    """Test the exception hierarchy and relationships."""

    def test_exception_inheritance_chain(self):
        """Test that all custom exceptions inherit properly."""
        errors = [
            WindburglrError("base"),
            MaxRetriesExceededError("max retries"),
            StaleWindObservationError("stale"),
            DuplicateObservationError("duplicate"),
        ]

        for error in errors:
            assert isinstance(error, Exception)
            if error != errors[0]:  # Skip base class
                assert isinstance(error, WindburglrError)

    def test_exception_raising(self):
        """Test that exceptions can be raised and caught."""
        with pytest.raises(WindburglrError):
            raise WindburglrError("Test error")

        with pytest.raises(MaxRetriesExceededError):
            raise MaxRetriesExceededError("Max retries")

        with pytest.raises(StaleWindObservationError):
            raise StaleWindObservationError("Stale data")

        with pytest.raises(DuplicateObservationError):
            raise DuplicateObservationError("Duplicate data")
