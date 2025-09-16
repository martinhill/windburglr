import asyncio
import json
import logging
import sys
from collections.abc import Awaitable, Callable
from datetime import datetime, UTC

import aiohttp
from aiohttp.web import HTTPClientError

from .config import Config, StationConfig
from .models import MaxRetriesExceededError, StaleWindObservationError, WindObs

logger = logging.getLogger(__name__)


class ObservationTracker:
    def __init__(self):
        self.last_obs_time: dict[str, datetime] = {}

    def is_new_obs(self, obs: WindObs) -> bool:
        station_last_obs_time = self.last_obs_time.get(obs.station)
        return not station_last_obs_time or station_last_obs_time < obs.timestamp

    def set_obs_last_timestamp(self, obs: WindObs):
        self.last_obs_time[obs.station] = obs.timestamp

    def get_last_obs_time(self, station: str) -> datetime | None:
        return self.last_obs_time.get(station)


class RetryHandler:
    def __init__(self, max_retries: int = 10, retry_delay: int = 5):
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    async def execute_with_retry(self, func: Callable[[], Awaitable], *args, **kwargs):
        retry_count = 0
        while True:
            try:
                return await func(*args, **kwargs)
            except (aiohttp.ClientResponseError, HTTPClientError) as e:
                # Further retries will not succeed, so don't retry
                raise e
            except Exception as e:
                if retry_count < self.max_retries:
                    logger.info(f"Error: {e}, retrying...")
                    await asyncio.sleep(self.retry_delay)
                    retry_count += 1
                else:
                    raise MaxRetriesExceededError("max retries exceeded") from e


# Callables
DataRequester = Callable[[], Awaitable[str]]
Parser = Callable[[str, StationConfig], WindObs]
OutputHandler = Callable[[WindObs], Awaitable[None]]
StatusHandler = Callable[[str, str, str | None], Awaitable[None]]


class WebRequesterContext:
    def __init__(self, config: Config):
        self.config = config

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.session.close()

    def create_requester(self, station_config: StationConfig) -> DataRequester:
        async def fetch_raw_data() -> str:
            headers = station_config.headers or {}
            response = await self.session.get(
                station_config.url,
                timeout=aiohttp.ClientTimeout(total=station_config.timeout),
                headers=headers,
            )
            response.raise_for_status()
            return await response.text()

        return fetch_raw_data


def create_json_parser(station_config: StationConfig) -> Parser:
    value_lookup = {"": None, "CALM": 0, "?": None, "--": None}

    def coerce_int(x):
        try:
            return value_lookup[x]
        except KeyError:
            return int(x)

    def coerce_float(x):
        if x is None:
            return 0.0
        try:
            val = value_lookup[x]
            return 0.0 if val is None else float(val)
        except KeyError:
            return float(x)

    def json_to_wind_obs(raw_data: str) -> WindObs:
        """Parse raw JSON to WindObs"""
        sensor_data = json.loads(raw_data)["v2"]["sensor_data"][station_config.name]

        wind_dir = sensor_data.get("wind_magnetic_dir_2_mean")
        wind_speed = sensor_data.get("wind_speed_2_mean") or 0
        wind_gust = sensor_data.get("gust_squall_speed")

        updated_text = sensor_data.get("observation_time")
        try:
            updated = datetime.strptime(updated_text, "%Y-%m-%d %H:%M")
            # tz = zoneinfo.ZoneInfo(station_config.timezone)
            updated = updated.replace(tzinfo=station_config.timezone)
        except ValueError as ex:
            sys.stdout.write(f'ValueError {ex}: updated_text="{updated_text}"\n')
            raise

        return WindObs(
            station=station_config.name,
            direction=coerce_int(wind_dir) if wind_dir else None,
            speed=coerce_float(wind_speed) if wind_speed else 0.0,
            gust=coerce_float(wind_gust) if wind_gust else None,
            timestamp=updated,
        )

    return json_to_wind_obs


class Scraper:
    tracker = ObservationTracker()

    def __init__(
        self,
        station_config: StationConfig,
        data_requester: DataRequester,
        parser: Parser,
        output_handler: OutputHandler,
        status_handler: StatusHandler,
        tracker: ObservationTracker,
        retry_handler: RetryHandler,
    ):
        self.station_config = station_config
        self.data_requester = data_requester
        self.parser = parser
        self.output_handler = output_handler
        self.status_handler = status_handler
        self.tracker = tracker
        self.retry_handler = retry_handler

    @classmethod
    def set_output_handler(cls, output_handler: OutputHandler):
        cls.output_handler = output_handler

    @classmethod
    def set_status_handler(cls, status_handler: StatusHandler):
        cls.status_handler = status_handler

    @classmethod
    def create(
        cls,
        station_config: StationConfig,
        data_requester: DataRequester,
        parser: Parser,
    ):
        """Factory method to create a Scraper instance."""
        if cls.output_handler is None:
            raise ValueError("Output handler not set")
        if cls.status_handler is None:
            raise ValueError("Status handler not set")
        return cls(
            station_config,
            data_requester,
            parser,
            cls.output_handler,
            cls.status_handler,
            cls.tracker,
            RetryHandler(),
        )

    async def fetch_and_process(self):
        """Fetches and processes wind observations for a station.
        Calls injected I/O and parsing handlers in sequence and handles exceptions.
        Does not do scheduling.
        """
        station = self.station_config.name
        try:
            logger.debug("Fetching data for station %s", station)
            raw_data = await self.retry_handler.execute_with_retry(self.data_requester)
            logger.debug("Parsing data for station %s", station)
            obs = self.parser(raw_data)
            if self.tracker.is_new_obs(obs):
                self.tracker.set_obs_last_timestamp(obs)
                logger.debug("Emitting new observation for station %s", station)
                await self.output_handler(obs)
                await self.status_handler(station, "healthy", None)
            else:
                # Check if we should mark as stale based on elapsed time
                last_successful_time = self.tracker.get_last_obs_time(station)
                current_time = datetime.now(UTC)

                if last_successful_time:
                    elapsed_seconds = (
                        current_time - last_successful_time
                    ).total_seconds()
                    if elapsed_seconds >= self.station_config.stale_data_timeout:
                        logger.info(
                            "Stale data for station %s (elapsed: %.1fs)",
                            station,
                            elapsed_seconds,
                        )
                        await self.status_handler(
                            station,
                            "stale_data",
                            f"stale data: timestamp={obs.timestamp}, elapsed={elapsed_seconds:.1f}s",
                        )
                        raise StaleWindObservationError(
                            f"stale data: station={station} timestamp={obs.timestamp}, elapsed={elapsed_seconds:.1f}s"
                        )
                    else:
                        logger.info(
                            "Duplicate data for station %s (elapsed: %.1fs, timeout: %ds)",
                            station,
                            elapsed_seconds,
                            self.station_config.stale_data_timeout,
                        )
                        # Don't raise error for duplicate data within timeout period
                        return
                else:
                    # First observation, set as successful
                    self.tracker.set_successful_obs_timestamp(obs)
                    logger.debug("First observation for station %s", station)
                    await self.output_handler(obs)
                    await self.status_handler(station, "healthy", None)
        except aiohttp.ClientResponseError as e:
            error_msg = f"HTTP {e.status}: {e.message}"
            await self.status_handler(station, "network_error", error_msg)
            raise
        except (ValueError, json.JSONDecodeError) as e:
            error_msg = f"Parse error: {e}"
            await self.status_handler(station, "parse_error", error_msg)
            raise
        except TimeoutError:
            error_msg = "Network timeout"
            await self.status_handler(station, "network_error", error_msg)
            raise
        except StaleWindObservationError:
            # Already handled above, just re-raise
            raise
        except Exception as e:
            error_msg = f"Unexpected error: {e}"
            await self.status_handler(station, "error", error_msg)
            raise
