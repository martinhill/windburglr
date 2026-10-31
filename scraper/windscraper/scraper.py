import asyncio
import base64
import json
import logging
import re
import sys
from collections.abc import Awaitable, Callable
from dataclasses import fields
from datetime import UTC, datetime, tzinfo
from typing import Any
from urllib.parse import urljoin

import aiohttp
import sentry_sdk
from aiohttp.web import HTTPClientError
from Crypto.Cipher import AES  # pyright: ignore[reportMissingModuleSource]
from Crypto.Util.Padding import unpad  # pyright: ignore[reportMissingModuleSource]

from .config import Config, StationConfig
from .models import (
    ConfigurationError,
    MaxRetriesExceededError,
    StaleWindObservationError,
    WindburglrError,
    WindObs,
)

logger = logging.getLogger(__name__)


def _get_nested_value(data: dict[str, Any], path: str) -> Any:
    keys = path.split(".")
    value: Any = data
    for key in keys:
        if isinstance(value, dict):
            value = value.get(key)
            if value is None:
                return None
        else:
            return None
    return value


def station_config_context(station_config: StationConfig) -> dict[str, Any]:
    """The complete station config, in a form Sentry can serialize."""
    context: dict[str, Any] = {}
    for f in fields(station_config):
        value = getattr(station_config, f.name)
        context[f.name] = str(value) if isinstance(value, tzinfo) else value
    return context


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
Parser = Callable[[str], WindObs]
ParserFactory = Callable[[], Awaitable[Parser]]
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


def create_base64_decoder(inner: Parser) -> Parser:
    """Wrap a parser with a base64 decoding step."""

    def decode_and_parse(raw_data: str) -> WindObs:
        decoded = base64.b64decode(raw_data.strip())
        return inner(decoded.decode("latin-1"))

    return decode_and_parse


def create_aes256cbc_decryptor(key: bytes, inner: Parser) -> Parser:
    """Wrap a parser with an AES-256-CBC decryption step.

    The ciphertext is expected to have the 16-byte IV prepended.
    """

    def decrypt_and_parse(raw_data: str) -> WindObs:
        ciphertext = raw_data.encode("latin-1")
        iv = ciphertext[:16]
        cipher = AES.new(key, AES.MODE_CBC, iv)
        plaintext = unpad(cipher.decrypt(ciphertext[16:]), AES.block_size)
        return inner(plaintext.decode("utf-8"))

    return decrypt_and_parse


async def _fetch_text(session: aiohttp.ClientSession, url: str) -> str:
    async with session.get(url) as response:
        # Ignore 404 status response.raise_for_status()
        return await response.text()


async def _fetch_key(
    session: aiohttp.ClientSession,
    key_url: str,
    key_extract_regex: str,
    station_name: str,
    key_asset_regex: str | None = None,
) -> bytes:
    """Fetch decryption key from a URL and extract it using a regex.

    If ``key_asset_regex`` is given, the ``key_url`` page is first searched for
    an asset path (e.g. a content-hashed JS bundle), which is resolved relative
    to ``key_url`` and fetched; ``key_extract_regex`` is then applied to the asset.
    """
    text = await _fetch_text(session, key_url)
    if key_asset_regex:
        match = re.search(key_asset_regex, text)
        if not match:
            raise ValueError(
                f"key_asset_regex {key_asset_regex!r} produced no match for station {station_name}"
            )
        asset_url = urljoin(key_url, match.group(1))
        logger.debug("Fetching key asset %s for station %s", asset_url, station_name)
        text = await _fetch_text(session, asset_url)
    match = re.search(key_extract_regex, text)
    if not match:
        raise ValueError(
            f"key_extract_regex {key_extract_regex!r} produced no match for station {station_name}"
        )
    return match.group(1).encode("utf-8")


async def create_parser(
    station_config: StationConfig,
    session: aiohttp.ClientSession,
) -> Parser:
    """Factory that returns the appropriate Parser for a station.

    Reads ``station_config.parser`` (currently only ``"json"`` is supported),
    then wraps the inner parser with decryption and/or decoding layers as
    dictated by ``station_config.encryption`` and ``station_config.encoding``.

    Layer order (outermost → innermost):
        encoding  →  encryption  →  json parser

    Supported values:
        encoding:   ``"base64"``
        encryption: ``"aes256cbc"``
    """
    inner: Parser = create_json_parser(station_config)

    if station_config.encryption == "aes256cbc":
        if not station_config.key_url or not station_config.key_extract_regex:
            raise ValueError(
                f"station {station_config.name}: key_url and key_extract_regex are required for aes256cbc"
            )
        key = await _fetch_key(
            session,
            station_config.key_url,
            station_config.key_extract_regex,
            station_config.name,
            station_config.key_asset_regex,
        )
        logger.info("Fetched decryption key for station %s", station_config.name)
        inner = create_aes256cbc_decryptor(key, inner)
    elif station_config.encryption is not None:
        raise ValueError(
            f"station {station_config.name}: unsupported encryption {station_config.encryption!r}"
        )

    if station_config.encoding == "base64":
        inner = create_base64_decoder(inner)
    elif station_config.encoding is not None:
        raise ValueError(
            f"station {station_config.name}: unsupported encoding {station_config.encoding!r}"
        )

    return inner


def create_json_parser(station_config: StationConfig) -> Parser:
    def json_to_wind_obs(raw_data: str) -> WindObs:
        data = json.loads(raw_data)

        wind_dir = _get_nested_value(data, station_config.direction_path)
        wind_speed = _get_nested_value(data, station_config.speed_path) or 0
        wind_gust = _get_nested_value(data, station_config.gust_path)
        updated_text = _get_nested_value(data, station_config.timestamp_path)

        try:
            updated = datetime.strptime(updated_text, station_config.timestamp_format)
            updated = updated.replace(tzinfo=station_config.timezone)
        except ValueError as ex:
            sys.stdout.write(f'ValueError {ex}: updated_text="{updated_text}"\n')
            raise

        return WindObs(
            station=station_config.name,
            direction=wind_dir,
            speed=wind_speed,
            gust=wind_gust,
            timestamp=updated,
        )

    return json_to_wind_obs


class Scraper:
    # Shared class-level instance of ObservationTracker works since it tracks observations by station,
    # and there is only one Scraper instance per station.
    tracker: ObservationTracker = ObservationTracker()

    def __init__(
        self,
        station_config: StationConfig,
        data_requester: DataRequester,
        parser: Parser | None,
        output_handler: OutputHandler,
        status_handler: StatusHandler,
        tracker: ObservationTracker,
        retry_handler: RetryHandler,
        parser_factory: ParserFactory | None = None,
    ):
        """Either ``parser`` or ``parser_factory`` is required. With a factory, the parser
        is created on first use, and created again after a parse failure, so a decryption
        key that changed is fetched again."""
        self.station_config = station_config
        self.data_requester = data_requester
        self.parser = parser
        self.parser_factory = parser_factory
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
        parser: Parser | None = None,
        parser_factory: ParserFactory | None = None,
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
            parser_factory,
        )

    async def _get_parser(self) -> Parser:
        if self.parser is None:
            if self.parser_factory is None:
                raise ValueError("Scraper has neither a parser nor a parser factory")
            try:
                self.parser = await self.parser_factory()
            except ValueError as e:
                # Key not found, or invalid config; network errors propagate as they are
                raise ConfigurationError(f"Parser setup failed: {e}") from e
        return self.parser

    async def run_once(self):
        """Fetch and process once, logging any failure for this station.

        Runs in its own Sentry isolation scope, so events (and breadcrumbs) from this
        station's processing carry its tag and complete config, and don't mix with those
        of stations processed concurrently.
        """
        station = self.station_config.name
        with sentry_sdk.isolation_scope() as scope:
            scope.set_tag("station", station)
            scope.set_context(
                "station_config", station_config_context(self.station_config)
            )
            try:
                await self.fetch_and_process()
            except ConfigurationError:
                logger.error(
                    "Configuration error for station %s", station, exc_info=True
                )
                raise
            except WindburglrError as e:
                logger.warning("Handled exception for station %s: %s", station, e)
                raise
            except Exception:
                logger.exception("Unexpected error for station %s", station)
                raise

    async def fetch_and_process(self):
        """Fetches and processes wind observations for a station.
        Calls injected I/O and parsing handlers in sequence and handles exceptions.
        Does not do scheduling.
        """
        station = self.station_config.name
        try:
            logger.debug("Fetching data for station %s", station)
            raw_data = await self.retry_handler.execute_with_retry(self.data_requester)
            parser = await self._get_parser()
            logger.debug("Parsing data for station %s", station)
            try:
                obs = parser(raw_data)
            except Exception as e:
                if self.parser_factory:
                    # Start again from the factory next time, e.g. to fetch a changed key
                    self.parser = None
                raise ConfigurationError(f"Parse error: {e}") from e
            if self.tracker.is_new_obs(obs):
                self.tracker.set_obs_last_timestamp(obs)
                logger.debug("Emitting new observation for station %s", station)
                await self.output_handler(obs)
                await self.status_handler(station, "healthy", "")
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
                    self.tracker.set_obs_last_timestamp(obs)
                    logger.debug("First observation for station %s", station)
                    await self.output_handler(obs)
                    await self.status_handler(station, "healthy", "")
        except ConfigurationError as e:
            await self.status_handler(station, "parse_error", str(e))
            raise
        except aiohttp.ClientResponseError as e:
            error_msg = f"HTTP {e.status}: {e.message}"
            await self.status_handler(station, "http_error", error_msg)
            raise WindburglrError(error_msg) from e
        except (ValueError, json.JSONDecodeError) as e:
            error_msg = f"Parse error: {e}"
            await self.status_handler(station, "parse_error", error_msg)
            raise WindburglrError(error_msg) from e
        except TimeoutError as e:
            error_msg = "Network timeout"
            await self.status_handler(station, "network_error", error_msg)
            raise WindburglrError(error_msg) from e
        except StaleWindObservationError:
            # Already handled above, just re-raise
            raise
        except Exception as e:
            error_msg = f"Unexpected error: {e}"
            await self.status_handler(station, "error", error_msg)
            raise
