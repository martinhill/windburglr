import asyncio
import json
from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock, patch, Mock

import aiohttp
import pytest

from windscraper.config import StationConfig
from windscraper.models import (
    WindObs,
    MaxRetriesExceededError,
    StaleWindObservationError,
)
from windscraper.scraper import (
    ObservationTracker,
    RetryHandler,
    WebRequesterContext,
    Scraper,
    create_json_parser,
)


def test_observation_tracker_initialization():
    """Test ObservationTracker initialization."""
    tracker = ObservationTracker()
    assert tracker.last_obs_time == {}


def test_observation_tracker_is_new_obs_first_observation():
    """Test is_new_obs with first observation for a station."""
    tracker = ObservationTracker()
    obs = WindObs(
        station="TEST_STATION",
        direction=180,
        speed=15.5,
        gust=20.0,
        timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
    )
    assert tracker.is_new_obs(obs) is True


def test_observation_tracker_is_new_obs_newer_timestamp():
    """Test is_new_obs with newer timestamp."""
    tracker = ObservationTracker()
    obs = WindObs(
        station="TEST_STATION",
        direction=180,
        speed=15.5,
        gust=20.0,
        timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
    )

    # Set an older timestamp
    old_time = datetime(2024, 1, 1, 11, 0, 0, tzinfo=UTC)
    tracker.last_obs_time[obs.station] = old_time

    # New observation should be considered new
    assert tracker.is_new_obs(obs) is True


def test_observation_tracker_is_new_obs_same_timestamp():
    """Test is_new_obs with same timestamp."""
    tracker = ObservationTracker()
    obs = WindObs(
        station="TEST_STATION",
        direction=180,
        speed=15.5,
        gust=20.0,
        timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
    )

    # Set the same timestamp
    tracker.last_obs_time[obs.station] = obs.timestamp

    # Same timestamp should not be considered new
    assert tracker.is_new_obs(obs) is False


def test_observation_tracker_set_obs_last_timestamp():
    """Test set_obs_last_timestamp."""
    tracker = ObservationTracker()
    obs = WindObs(
        station="TEST_STATION",
        direction=180,
        speed=15.5,
        gust=20.0,
        timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
    )
    tracker.set_obs_last_timestamp(obs)

    assert tracker.last_obs_time[obs.station] == obs.timestamp


def test_create_json_parser_basic(
    sample_station_config: StationConfig, mock_raw_json_data: str
):
    """Test create_json_parser with basic JSON data."""
    parser = create_json_parser(sample_station_config)
    obs = parser(mock_raw_json_data)

    assert isinstance(obs, WindObs)
    assert obs.station == sample_station_config.name
    assert obs.direction == 180
    assert obs.speed == 15.5
    assert obs.gust == 20.0
    assert obs.timestamp == datetime(2024, 1, 1, 12, 0, tzinfo=UTC)


def test_create_json_parser_missing_fields(sample_station_config: StationConfig):
    """Test create_json_parser handles missing fields gracefully."""
    json_data = json.dumps(
        {
            "v2": {
                "sensor_data": {
                    "TEST_STATION": {
                        "wind_speed_2_mean": "10.0",
                        "observation_time": "2024-01-01 12:00",
                        # Missing direction and gust
                    }
                }
            }
        }
    )

    parser = create_json_parser(sample_station_config)
    obs = parser(json_data)

    assert obs.station == sample_station_config.name
    assert obs.direction is None
    assert obs.speed == 10.0
    assert obs.gust is None


def test_create_json_parser_invalid_json(sample_station_config: StationConfig):
    """Test create_json_parser raises exception for invalid JSON."""
    parser = create_json_parser(sample_station_config)

    try:
        parser("invalid json")
        assert False, "Should have raised JSONDecodeError"
    except json.JSONDecodeError:
        pass  # Expected


def test_create_json_parser_value_coercion(sample_station_config: StationConfig):
    """Test create_json_parser value coercion for special cases."""
    json_data = json.dumps(
        {
            "v2": {
                "sensor_data": {
                    "TEST_STATION": {
                        "wind_magnetic_dir_2_mean": "CALM",  # Should become 0
                        "wind_speed_2_mean": "?",  # Should become None
                        "gust_squall_speed": "--",  # Should become None
                        "observation_time": "2024-01-01 12:00",
                    }
                }
            }
        }
    )

    parser = create_json_parser(sample_station_config)
    obs = parser(json_data)

    assert obs.direction == 0  # CALM -> 0
    assert obs.speed == 0.0  # ? -> 0.0 (coerced to float)
    assert obs.gust == 0.0  # -- -> 0.0


def test_create_json_parser_invalid_timestamp(sample_station_config: StationConfig):
    """Test create_json_parser raises exception for invalid timestamp."""
    json_data = json.dumps(
        {
            "v2": {
                "sensor_data": {
                    "TEST_STATION": {
                        "wind_speed_2_mean": "10.0",
                        "observation_time": "invalid-timestamp",
                    }
                }
            }
        }
    )

    parser = create_json_parser(sample_station_config)

    try:
        parser(json_data)
        assert False, "Should have raised ValueError"
    except ValueError:
        pass  # Expected


class TestObservationTracker:
    """Test cases for ObservationTracker class."""

    def test_observation_tracker_initialization(self):
        """Test ObservationTracker initialization."""
        tracker = ObservationTracker()
        assert tracker.last_obs_time == {}

    def test_is_new_obs_first_observation(self, sample_wind_obs: WindObs):
        """Test is_new_obs with first observation for a station."""
        tracker = ObservationTracker()
        assert tracker.is_new_obs(sample_wind_obs) is True

    def test_is_new_obs_newer_timestamp(self, sample_wind_obs: WindObs):
        """Test is_new_obs with newer timestamp."""
        tracker = ObservationTracker()

        # Set an older timestamp
        old_time = datetime(2024, 1, 1, 11, 0, 0, tzinfo=UTC)
        tracker.last_obs_time[sample_wind_obs.station] = old_time

        # New observation should be considered new
        assert tracker.is_new_obs(sample_wind_obs) is True

    def test_is_new_obs_same_timestamp(self, sample_wind_obs: WindObs):
        """Test is_new_obs with same timestamp."""
        tracker = ObservationTracker()

        # Set the same timestamp
        tracker.last_obs_time[sample_wind_obs.station] = sample_wind_obs.timestamp

        # Same timestamp should not be considered new
        assert tracker.is_new_obs(sample_wind_obs) is False

    def test_is_new_obs_older_timestamp(self, sample_wind_obs: WindObs):
        """Test is_new_obs with older timestamp."""
        tracker = ObservationTracker()

        # Set a newer timestamp
        new_time = datetime(2024, 1, 1, 13, 0, 0, tzinfo=UTC)
        tracker.last_obs_time[sample_wind_obs.station] = new_time

        # Older timestamp should not be considered new
        assert tracker.is_new_obs(sample_wind_obs) is False

    def test_set_obs_last_timestamp(self, sample_wind_obs: WindObs):
        """Test set_obs_last_timestamp."""
        tracker = ObservationTracker()
        tracker.set_obs_last_timestamp(sample_wind_obs)

        assert (
            tracker.last_obs_time[sample_wind_obs.station] == sample_wind_obs.timestamp
        )

    def test_multiple_stations_tracking(self):
        """Test tracking multiple stations independently."""
        tracker = ObservationTracker()

        obs1 = WindObs(
            station="STATION_A",
            direction=180,
            speed=15.0,
            gust=20.0,
            timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
        )

        obs2 = WindObs(
            station="STATION_B",
            direction=90,
            speed=10.0,
            gust=15.0,
            timestamp=datetime(2024, 1, 1, 12, 30, 0, tzinfo=UTC),
        )

        # Both should be new initially
        assert tracker.is_new_obs(obs1) is True
        assert tracker.is_new_obs(obs2) is True

        # Set timestamps
        tracker.set_obs_last_timestamp(obs1)
        tracker.set_obs_last_timestamp(obs2)

        # Check timestamps are tracked separately
        assert tracker.last_obs_time["STATION_A"] == obs1.timestamp
        assert tracker.last_obs_time["STATION_B"] == obs2.timestamp

        # Same observations should not be new
        assert tracker.is_new_obs(obs1) is False
        assert tracker.is_new_obs(obs2) is False


class TestRetryHandler:
    """Test cases for RetryHandler class."""

    def test_retry_handler_initialization(self):
        """Test RetryHandler initialization."""
        handler = RetryHandler()
        assert handler.max_retries == 10
        assert handler.retry_delay == 5

    def test_retry_handler_custom_values(self):
        """Test RetryHandler with custom values."""
        handler = RetryHandler(max_retries=5, retry_delay=10)
        assert handler.max_retries == 5
        assert handler.retry_delay == 10

    @pytest.mark.asyncio
    async def test_execute_with_retry_success_first_try(self):
        """Test execute_with_retry succeeds on first try."""
        handler = RetryHandler()
        mock_func = AsyncMock(return_value="success")

        result = await handler.execute_with_retry(mock_func)

        assert result == "success"
        assert mock_func.call_count == 1

    @pytest.mark.asyncio
    async def test_execute_with_retry_success_after_retries(self):
        """Test execute_with_retry succeeds after some retries."""
        handler = RetryHandler(max_retries=3, retry_delay=0.1)  # Fast retry for test
        mock_func = AsyncMock(
            side_effect=[Exception("fail1"), Exception("fail2"), "success"]
        )

        result = await handler.execute_with_retry(mock_func)

        assert result == "success"
        assert mock_func.call_count == 3

    @pytest.mark.asyncio
    async def test_execute_with_retry_max_retries_exceeded(self):
        """Test execute_with_retry raises MaxRetriesExceededError after max retries."""
        handler = RetryHandler(max_retries=2, retry_delay=0.1)
        mock_func = AsyncMock(side_effect=Exception("persistent failure"))

        with pytest.raises(MaxRetriesExceededError):
            await handler.execute_with_retry(mock_func)

        assert mock_func.call_count == 3  # initial + 2 retries

    @pytest.mark.asyncio
    async def test_execute_with_retry_client_error_no_retry(self):
        """Test that ClientResponseError and HTTPClientError don't trigger retries."""
        handler = RetryHandler(max_retries=5)
        mock_request_info = MagicMock()
        mock_func = AsyncMock(
            side_effect=aiohttp.ClientResponseError(
                request_info=mock_request_info,
                status=404,
                message="Not Found",
                headers={},
                history=(),
            )
        )

        with pytest.raises(aiohttp.ClientResponseError):
            await handler.execute_with_retry(mock_func)

        assert mock_func.call_count == 1  # No retries for client errors

    @pytest.mark.asyncio
    async def test_execute_with_retry_http_client_error_no_retry(self):
        """Test that HTTPClientError doesn't trigger retries."""
        handler = RetryHandler(max_retries=5)
        mock_func = AsyncMock(side_effect=aiohttp.web.HTTPClientError())

        with pytest.raises(aiohttp.web.HTTPClientError):
            await handler.execute_with_retry(mock_func)

        assert mock_func.call_count == 1  # No retries for HTTP client errors

    @pytest.mark.asyncio
    @patch("asyncio.sleep")
    async def test_execute_with_retry_uses_delay(self, mock_sleep):
        """Test that execute_with_retry uses the specified delay between retries."""
        handler = RetryHandler(max_retries=2, retry_delay=1.5)
        mock_func = AsyncMock(side_effect=[Exception("fail"), "success"])

        await handler.execute_with_retry(mock_func)

        mock_sleep.assert_called_once_with(1.5)


class TestWebRequesterContext:
    """Test cases for WebRequesterContext class."""

    def test_web_requester_context_initialization(self, sample_config):
        """Test WebRequesterContext initialization."""
        context = WebRequesterContext(sample_config)
        assert context.config == sample_config

    @pytest.mark.asyncio
    async def test_web_requester_context_aenter_aexit(self, sample_config):
        """Test WebRequesterContext context manager."""
        context = WebRequesterContext(sample_config)

        async with context:
            assert hasattr(context, "session")
            assert isinstance(context.session, aiohttp.ClientSession)

        # Session should be closed after exiting context
        assert context.session.closed

    @pytest.mark.asyncio
    async def test_create_requester(self, sample_config, sample_station_config):
        """Test create_requester method."""
        context = WebRequesterContext(sample_config)

        async with context:
            requester = context.create_requester(sample_station_config)

            # Mock the session.get method
            mock_response = AsyncMock()
            mock_response.text.return_value = '{"test": "data"}'
            mock_response.raise_for_status = Mock(return_value=None)
            context.session.get = AsyncMock(return_value=mock_response)

            result = await requester()

            assert result == '{"test": "data"}'
            context.session.get.assert_called_once_with(
                sample_station_config.url,
                timeout=aiohttp.ClientTimeout(total=sample_station_config.timeout),
                headers=sample_station_config.headers,
            )

    @pytest.mark.asyncio
    async def test_create_requester_with_exception(
        self, sample_config, sample_station_config
    ):
        """Test create_requester handles exceptions properly."""
        context = WebRequesterContext(sample_config)

        async with context:
            requester = context.create_requester(sample_station_config)

            # Mock session.get to raise an exception
            mock_request_info = MagicMock()
            context.session.get = AsyncMock(
                side_effect=aiohttp.ClientResponseError(
                    request_info=mock_request_info,
                    status=500,
                    message="Server Error",
                    headers={},
                    history=(),
                )
            )

            with pytest.raises(aiohttp.ClientResponseError):
                await requester()


class TestCreateJsonParser:
    """Test cases for create_json_parser function."""

    def test_create_json_parser_basic(self, sample_station_config, mock_raw_json_data):
        """Test create_json_parser with basic JSON data."""
        parser = create_json_parser(sample_station_config)
        obs = parser(mock_raw_json_data)

        assert isinstance(obs, WindObs)
        assert obs.station == sample_station_config.name
        assert obs.direction == 180
        assert obs.speed == 15.5
        assert obs.gust == 20.0
        assert obs.timestamp == datetime(2024, 1, 1, 12, 0, tzinfo=UTC)

    def test_create_json_parser_missing_fields(self, sample_station_config):
        """Test create_json_parser handles missing fields gracefully."""
        json_data = json.dumps(
            {
                "v2": {
                    "sensor_data": {
                        "TEST_STATION": {
                            "wind_speed_2_mean": "10.0",
                            "observation_time": "2024-01-01 12:00",
                            # Missing direction and gust
                        }
                    }
                }
            }
        )

        parser = create_json_parser(sample_station_config)
        obs = parser(json_data)

        assert obs.station == sample_station_config.name
        assert obs.direction is None
        assert obs.speed == 10.0
        assert obs.gust is None

    def test_create_json_parser_invalid_json(self, sample_station_config):
        """Test create_json_parser raises exception for invalid JSON."""
        parser = create_json_parser(sample_station_config)

        with pytest.raises(json.JSONDecodeError):
            parser("invalid json")

    def test_create_json_parser_value_coercion(self, sample_station_config):
        """Test create_json_parser value coercion for special cases."""
        json_data = json.dumps(
            {
                "v2": {
                    "sensor_data": {
                        "TEST_STATION": {
                            "wind_magnetic_dir_2_mean": "CALM",  # Should become 0
                            "wind_speed_2_mean": "?",  # Should become None
                            "gust_squall_speed": "--",  # Should become None
                            "observation_time": "2024-01-01 12:00",
                        }
                    }
                }
            }
        )

        parser = create_json_parser(sample_station_config)
        obs = parser(json_data)

        assert obs.direction == 0  # CALM -> 0
        assert obs.speed == 0.0  # ? -> 0.0 (coerced to float)
        assert obs.gust == 0.0  # -- -> 0.0

    def test_create_json_parser_invalid_timestamp(self, sample_station_config):
        """Test create_json_parser raises exception for invalid timestamp."""
        json_data = json.dumps(
            {
                "v2": {
                    "sensor_data": {
                        "TEST_STATION": {
                            "wind_speed_2_mean": "10.0",
                            "observation_time": "invalid-timestamp",
                        }
                    }
                }
            }
        )

        parser = create_json_parser(sample_station_config)

        with pytest.raises(ValueError):
            parser(json_data)


class TestScraper:
    """Test cases for Scraper class."""

    def test_scraper_initialization(self, sample_station_config):
        """Test Scraper initialization."""
        mock_data_requester = AsyncMock()
        mock_parser = MagicMock()
        mock_output_handler = AsyncMock()
        mock_status_handler = AsyncMock()
        mock_tracker = MagicMock()
        mock_retry_handler = MagicMock()

        scraper = Scraper(
            sample_station_config,
            mock_data_requester,
            mock_parser,
            mock_output_handler,
            mock_status_handler,
            mock_tracker,
            mock_retry_handler,
        )

        assert scraper.station_config == sample_station_config
        assert scraper.data_requester == mock_data_requester
        assert scraper.parser == mock_parser
        assert scraper.output_handler == mock_output_handler
        assert scraper.status_handler == mock_status_handler
        assert scraper.tracker == mock_tracker
        assert scraper.retry_handler == mock_retry_handler

    def test_scraper_set_handlers_class_method(self):
        """Test Scraper class method for setting handlers."""
        mock_output_handler = AsyncMock()
        mock_status_handler = AsyncMock()

        Scraper.set_output_handler(mock_output_handler)
        Scraper.set_status_handler(mock_status_handler)

        assert Scraper.output_handler == mock_output_handler
        assert Scraper.status_handler == mock_status_handler

    def test_scraper_create_factory_method(self, sample_station_config):
        """Test Scraper.create factory method."""
        mock_data_requester = AsyncMock()
        mock_parser = MagicMock()
        mock_output_handler = AsyncMock()
        mock_status_handler = AsyncMock()

        # Set class handlers
        Scraper.set_output_handler(mock_output_handler)
        Scraper.set_status_handler(mock_status_handler)

        scraper = Scraper.create(
            sample_station_config, mock_data_requester, mock_parser
        )

        assert isinstance(scraper, Scraper)
        assert scraper.station_config == sample_station_config
        assert scraper.data_requester == mock_data_requester
        assert scraper.parser == mock_parser
        assert scraper.output_handler == mock_output_handler
        assert scraper.status_handler == mock_status_handler

    def test_scraper_create_without_handlers_raises_error(self, sample_station_config):
        """Test Scraper.create raises error when handlers not set."""
        # Reset class handlers
        Scraper.output_handler = None
        Scraper.status_handler = None

        mock_data_requester = AsyncMock()
        mock_parser = MagicMock()

        with pytest.raises(ValueError, match="Output handler not set"):
            Scraper.create(sample_station_config, mock_data_requester, mock_parser)

    @pytest.mark.asyncio
    async def test_fetch_and_process_success_new_observation(
        self, sample_station_config, sample_wind_obs
    ):
        """Test fetch_and_process with successful new observation."""
        mock_data_requester = AsyncMock(return_value='{"test": "data"}')
        mock_parser = MagicMock(return_value=sample_wind_obs)
        mock_output_handler = AsyncMock()
        mock_status_handler = AsyncMock()
        mock_tracker = MagicMock()
        mock_tracker.is_new_obs.return_value = True
        mock_retry_handler = MagicMock()
        mock_retry_handler.execute_with_retry = AsyncMock(
            return_value='{"test": "data"}'
        )

        scraper = Scraper(
            sample_station_config,
            mock_data_requester,
            mock_parser,
            mock_output_handler,
            mock_status_handler,
            mock_tracker,
            mock_retry_handler,
        )

        await scraper.fetch_and_process()

        mock_retry_handler.execute_with_retry.assert_called_once_with(
            mock_data_requester
        )
        mock_parser.assert_called_once_with('{"test": "data"}')
        mock_tracker.is_new_obs.assert_called_once_with(sample_wind_obs)
        mock_tracker.set_obs_last_timestamp.assert_called_once_with(sample_wind_obs)
        mock_output_handler.assert_called_once_with(sample_wind_obs)
        mock_status_handler.assert_called_once_with(
            sample_station_config.name, "healthy", None
        )

    @pytest.mark.asyncio
    async def test_fetch_and_process_stale_observation(
        self, sample_station_config, sample_wind_obs
    ):
        """Test fetch_and_process with stale observation."""
        from datetime import timedelta

        mock_data_requester = AsyncMock(return_value='{"test": "data"}')
        mock_parser = MagicMock(return_value=sample_wind_obs)
        mock_output_handler = AsyncMock()
        mock_status_handler = AsyncMock()
        mock_tracker = MagicMock()
        mock_tracker.is_new_obs.return_value = False
        # Mock to return a time that's older than the timeout (300 seconds default)
        mock_tracker.get_last_successful_obs_time.return_value = datetime.now(
            UTC
        ) - timedelta(seconds=400)
        mock_retry_handler = MagicMock()
        mock_retry_handler.execute_with_retry = AsyncMock(
            return_value='{"test": "data"}'
        )

        scraper = Scraper(
            sample_station_config,
            mock_data_requester,
            mock_parser,
            mock_output_handler,
            mock_status_handler,
            mock_tracker,
            mock_retry_handler,
        )

        with pytest.raises(StaleWindObservationError):
            await scraper.fetch_and_process()

        mock_output_handler.assert_not_called()
        # Check that status_handler was called with stale_data
        mock_status_handler.assert_called_once()
        call_args = mock_status_handler.call_args
        assert call_args[0][1] == "stale_data"

    @pytest.mark.asyncio
    async def test_fetch_and_process_network_error(self, sample_station_config):
        """Test fetch_and_process with network error."""
        mock_data_requester = AsyncMock()
        mock_parser = MagicMock()
        mock_output_handler = AsyncMock()
        mock_status_handler = AsyncMock()
        mock_tracker = MagicMock()
        mock_retry_handler = MagicMock()
        mock_request_info = MagicMock()
        mock_retry_handler.execute_with_retry = AsyncMock(
            side_effect=aiohttp.ClientResponseError(
                request_info=mock_request_info,
                status=500,
                message="Server Error",
                headers={},
                history=(),
            )
        )

        scraper = Scraper(
            sample_station_config,
            mock_data_requester,
            mock_parser,
            mock_output_handler,
            mock_status_handler,
            mock_tracker,
            mock_retry_handler,
        )

        with pytest.raises(aiohttp.ClientResponseError):
            await scraper.fetch_and_process()

        mock_parser.assert_not_called()
        mock_output_handler.assert_not_called()
        mock_status_handler.assert_called_once_with(
            sample_station_config.name, "network_error", "HTTP 500: Server Error"
        )

    @pytest.mark.asyncio
    async def test_fetch_and_process_parse_error(self, sample_station_config):
        """Test fetch_and_process with parse error."""
        mock_data_requester = AsyncMock(return_value='{"test": "data"}')
        mock_parser = MagicMock(side_effect=json.JSONDecodeError("Invalid JSON", "", 0))
        mock_output_handler = AsyncMock()
        mock_status_handler = AsyncMock()
        mock_tracker = MagicMock()
        mock_retry_handler = MagicMock()
        mock_retry_handler.execute_with_retry = AsyncMock(
            return_value='{"test": "data"}'
        )

        scraper = Scraper(
            sample_station_config,
            mock_data_requester,
            mock_parser,
            mock_output_handler,
            mock_status_handler,
            mock_tracker,
            mock_retry_handler,
        )

        with pytest.raises(json.JSONDecodeError):
            await scraper.fetch_and_process()

        mock_output_handler.assert_not_called()
        # Check that parse_error was called (may be called multiple times due to error handling)
        mock_status_handler.assert_any_call(
            sample_station_config.name,
            "parse_error",
            "Parse error: Invalid JSON: line 1 column 1 (char 0)",
        )

    @pytest.mark.asyncio
    async def test_fetch_and_process_timeout_error(self, sample_station_config):
        """Test fetch_and_process with timeout error."""
        mock_data_requester = AsyncMock()
        mock_parser = MagicMock()
        mock_output_handler = AsyncMock()
        mock_status_handler = AsyncMock()
        mock_tracker = MagicMock()
        mock_retry_handler = MagicMock()
        mock_retry_handler.execute_with_retry = AsyncMock(
            side_effect=asyncio.TimeoutError()
        )

        scraper = Scraper(
            sample_station_config,
            mock_data_requester,
            mock_parser,
            mock_output_handler,
            mock_status_handler,
            mock_tracker,
            mock_retry_handler,
        )

        with pytest.raises(TimeoutError):
            await scraper.fetch_and_process()

        mock_parser.assert_not_called()
        mock_output_handler.assert_not_called()
        mock_status_handler.assert_called_once_with(
            sample_station_config.name, "network_error", "Network timeout"
        )

    @pytest.mark.asyncio
    async def test_fetch_and_process_unexpected_error(self, sample_station_config):
        """Test fetch_and_process with unexpected error."""
        mock_data_requester = AsyncMock(return_value='{"test": "data"}')
        mock_parser = MagicMock(side_effect=Exception("Unexpected error"))
        mock_output_handler = AsyncMock()
        mock_status_handler = AsyncMock()
        mock_tracker = MagicMock()
        mock_retry_handler = MagicMock()
        mock_retry_handler.execute_with_retry = AsyncMock(
            return_value='{"test": "data"}'
        )

        scraper = Scraper(
            sample_station_config,
            mock_data_requester,
            mock_parser,
            mock_output_handler,
            mock_status_handler,
            mock_tracker,
            mock_retry_handler,
        )

        with pytest.raises(Exception, match="Unexpected error"):
            await scraper.fetch_and_process()

        mock_output_handler.assert_not_called()
        mock_status_handler.assert_called_once_with(
            sample_station_config.name, "error", "Unexpected error: Unexpected error"
        )

    @pytest.mark.asyncio
    async def test_fetch_and_process_stale_data_timeout_not_exceeded(
        self, sample_station_config, sample_wind_obs
    ):
        """Test fetch_and_process with duplicate data within stale timeout period."""
        from datetime import timedelta
        from unittest.mock import patch

        # Create station config with short timeout for testing
        station_config = StationConfig(
            name="TEST_STATION",
            url="https://example.com/api/test",
            timeout=10,
            stale_data_timeout=60,  # 1 minute timeout
        )

        mock_data_requester = AsyncMock(return_value='{"test": "data"}')
        mock_parser = MagicMock(return_value=sample_wind_obs)
        mock_output_handler = AsyncMock()
        mock_status_handler = AsyncMock()
        mock_tracker = MagicMock()
        mock_retry_handler = MagicMock()
        mock_retry_handler.execute_with_retry = AsyncMock(
            return_value='{"test": "data"}'
        )

        # Mock tracker to simulate duplicate observation
        mock_tracker.is_new_obs.return_value = False
        mock_tracker.get_last_successful_obs_time.return_value = datetime.now(
            UTC
        ) - timedelta(seconds=30)  # 30 seconds ago

        scraper = Scraper(
            station_config,
            mock_data_requester,
            mock_parser,
            mock_output_handler,
            mock_status_handler,
            mock_tracker,
            mock_retry_handler,
        )

        # Should not raise StaleWindObservationError when within timeout
        await scraper.fetch_and_process()

        # Should not call output handler for duplicate data
        mock_output_handler.assert_not_called()
        # Should not call status handler with stale_data
        mock_status_handler.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_and_process_stale_data_timeout_exceeded(
        self, sample_station_config, sample_wind_obs
    ):
        """Test fetch_and_process with duplicate data after stale timeout period."""
        from datetime import timedelta
        from unittest.mock import patch

        # Create station config with short timeout for testing
        station_config = StationConfig(
            name="TEST_STATION",
            url="https://example.com/api/test",
            timeout=10,
            stale_data_timeout=60,  # 1 minute timeout
        )

        mock_data_requester = AsyncMock(return_value='{"test": "data"}')
        mock_parser = MagicMock(return_value=sample_wind_obs)
        mock_output_handler = AsyncMock()
        mock_status_handler = AsyncMock()
        mock_tracker = MagicMock()
        mock_retry_handler = MagicMock()
        mock_retry_handler.execute_with_retry = AsyncMock(
            return_value='{"test": "data"}'
        )

        # Mock tracker to simulate duplicate observation
        mock_tracker.is_new_obs.return_value = False
        mock_tracker.get_last_successful_obs_time.return_value = datetime.now(
            UTC
        ) - timedelta(seconds=90)  # 90 seconds ago

        scraper = Scraper(
            station_config,
            mock_data_requester,
            mock_parser,
            mock_output_handler,
            mock_status_handler,
            mock_tracker,
            mock_retry_handler,
        )

        # Should raise StaleWindObservationError when timeout exceeded
        with pytest.raises(StaleWindObservationError):
            await scraper.fetch_and_process()

        # Should not call output handler for stale data
        mock_output_handler.assert_not_called()
        # Should call status handler with stale_data
        mock_status_handler.assert_called_once()
        call_args = mock_status_handler.call_args
        assert call_args[0][1] == "stale_data"  # status parameter

    @pytest.mark.asyncio
    async def test_fetch_and_process_first_observation_sets_successful_timestamp(
        self, sample_station_config, sample_wind_obs
    ):
        """Test that first observation sets successful timestamp."""
        mock_data_requester = AsyncMock(return_value='{"test": "data"}')
        mock_parser = MagicMock(return_value=sample_wind_obs)
        mock_output_handler = AsyncMock()
        mock_status_handler = AsyncMock()
        mock_tracker = MagicMock()
        mock_retry_handler = MagicMock()
        mock_retry_handler.execute_with_retry = AsyncMock(
            return_value='{"test": "data"}'
        )

        # Mock tracker to simulate first observation
        mock_tracker.is_new_obs.return_value = False
        mock_tracker.get_last_successful_obs_time.return_value = (
            None  # No previous successful observation
        )

        scraper = Scraper(
            sample_station_config,
            mock_data_requester,
            mock_parser,
            mock_output_handler,
            mock_status_handler,
            mock_tracker,
            mock_retry_handler,
        )

        await scraper.fetch_and_process()

        # Should call output handler for first observation
        mock_output_handler.assert_called_once_with(sample_wind_obs)
        # Should set successful timestamp
        mock_tracker.set_successful_obs_timestamp.assert_called_once_with(
            sample_wind_obs
        )
        # Should call status handler with healthy
        mock_status_handler.assert_called_once_with(
            sample_station_config.name, "healthy", None
        )
