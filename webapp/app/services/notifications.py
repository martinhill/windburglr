import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import asyncpg

from ..cache.abc import CacheBackend
from ..models import ScraperStatus, WindDataPoint
from .watchdog import WatchdogService
from .websocket import WebSocketManager

logger = logging.getLogger("windburglr.notifications")

ListenerConnector = Callable[[], Awaitable[asyncpg.Connection]]

CHANNELS = ("wind_obs_insert", "scraper_status_update")


class PostgresNotificationManager:
    """Manages Postgres LISTEN/NOTIFY connections for real-time updates.

    `start()` makes one bounded connection attempt, then a supervisor task keeps the
    connection alive: it reconnects with exponential backoff whenever the connection is
    lost or an attempt fails, and never gives up while the app is running.
    """

    def __init__(
        self,
        cache_backend: CacheBackend,
        websocket_manager: WebSocketManager,
        connect: ListenerConnector,
        watchdog_service: WatchdogService | None = None,
        postgres_monitor_interval: float = 30.0,
        on_reconnect: Callable[[], Awaitable[None]] | None = None,
        initial_retry_delay: float = 1.0,
        max_retry_delay: float = 60.0,
    ):
        self.cache_backend = cache_backend
        self.websocket_manager = websocket_manager
        self.watchdog_service = watchdog_service
        self.postgres_monitor_interval = postgres_monitor_interval
        self.initial_retry_delay = initial_retry_delay
        self.max_retry_delay = max_retry_delay
        self._connect_listener = connect
        # Called after a reconnection, when notifications may have been missed
        self._on_reconnect = on_reconnect
        self.pg_listener: asyncpg.Connection | None = None
        self.notification_count = 0
        self.connect_attempts = 0
        self.monitor_task: asyncio.Task | None = None
        self._is_pg_listener_healthy = False
        self._has_connected = False
        self._connection_lost = asyncio.Event()

    async def start(self, connect_timeout: float = 5.0) -> None:
        """Connect the listener and start supervising it.

        A failed or slow first attempt doesn't fail startup; the supervisor retries.
        """
        connected = False
        try:
            connected = await asyncio.wait_for(self._connect(), timeout=connect_timeout)
        except TimeoutError:
            logger.error(
                "Postgres listener did not connect within %.0fs", connect_timeout
            )
        self.monitor_task = asyncio.create_task(
            self._supervise(connected), name="pg-listener-supervisor"
        )
        logger.info(
            "Postgres connection monitoring started, interval=%s",
            self.postgres_monitor_interval,
        )

    async def stop(self) -> None:
        """Stop supervising and close the listener connection."""
        if self.monitor_task and not self.monitor_task.done():
            self.monitor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.monitor_task
            logger.info("Postgres connection monitor stopped")

        connection, self.pg_listener = self.pg_listener, None
        self._is_pg_listener_healthy = False
        if connection:
            try:
                await asyncio.wait_for(connection.close(), timeout=5.0)
                logger.info("Postgres listener stopped")
            except Exception as e:
                logger.warning("Error closing Postgres listener, aborting it: %s", e)
                connection.terminate()

    async def _connect(self) -> bool:
        """Open a listener connection and subscribe; return whether it worked."""
        self.connect_attempts += 1
        connection = None
        try:
            connection = await self._connect_listener()
            await connection.add_listener(CHANNELS[0], self._handle_notification)
            await connection.add_listener(
                CHANNELS[1], self._handle_scraper_status_notification
            )
            connection.add_termination_listener(self._on_connection_terminated)
            # Load scraper status after subscribing, so no update falls in between
            if self.watchdog_service:
                await self.watchdog_service.initialize(connection)
        except BaseException as e:
            if connection is not None:
                connection.terminate()
            if not isinstance(e, Exception):
                raise
            logger.error("Failed to start Postgres listener: %s", e)
            self._is_pg_listener_healthy = False
            return False

        self.pg_listener = connection
        self._connection_lost.clear()
        self._is_pg_listener_healthy = True
        logger.info("Postgres listener started, listening on %s", ", ".join(CHANNELS))

        reconnected, self._has_connected = self._has_connected, True
        if reconnected and self._on_reconnect:
            try:
                await self._on_reconnect()
            except Exception as e:
                logger.error("Error in Postgres listener reconnect callback: %s", e)
        return True

    def _on_connection_terminated(self, connection: asyncpg.Connection) -> None:
        """Wake the supervisor as soon as the listener connection closes."""
        if connection is self.pg_listener:
            logger.warning("Postgres listener connection closed")
            self._is_pg_listener_healthy = False
            self._connection_lost.set()

    async def _check_pg_connection_health(self) -> bool:
        """Check if Postgres listener connection is healthy."""
        if not self.pg_listener or self.pg_listener.is_closed():
            self._is_pg_listener_healthy = False
            return False

        try:
            # Simple health check query
            await self.pg_listener.fetchval("SELECT 1")
            self._is_pg_listener_healthy = True
            return True
        except Exception as e:
            logger.warning("Postgres connection health check failed: %s", e)
            self._is_pg_listener_healthy = False
            return False

    def _discard_listener(self) -> None:
        connection, self.pg_listener = self.pg_listener, None
        if connection and not connection.is_closed():
            connection.terminate()

    @property
    def is_pg_listener_healthy(self) -> bool:
        """Check if Postgres listener is healthy."""
        return self._is_pg_listener_healthy

    async def _supervise(self, connected: bool):
        """Keep the listener connected and periodically check for stale scraper status."""
        retry_delay = self.initial_retry_delay
        while True:
            try:
                if not connected:
                    logger.warning(
                        "Retrying Postgres listener connection in %.1fs", retry_delay
                    )
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, self.max_retry_delay)
                    self._discard_listener()
                    connected = await self._connect()
                    continue
                retry_delay = self.initial_retry_delay

                # In case of scraper process being suspended, scraper status notifications would not be sent.
                # Periodically check for stale statuses
                if self.watchdog_service:
                    await self.watchdog_service.check_and_update_stale_statuses()

                # Sleep until the next check, or until the connection drops
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(
                        self._connection_lost.wait(),
                        timeout=self.postgres_monitor_interval,
                    )
                logger.debug("Postgres connection monitor running")
                connected = await self._check_pg_connection_health()
                if not connected:
                    logger.warning("Postgres listener connection lost")

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("Error in Postgres connection monitor: %s", e)
                await asyncio.sleep(5)  # Shorter wait on error

    async def _handle_notification(self, connection, pid, channel, payload):
        """Handle incoming Postgres notifications."""
        try:
            self.notification_count += 1
            logger.debug(
                "🔔 Received notification #%s on channel '%s' from PID %s",
                self.notification_count,
                channel,
                pid,
            )
            logger.debug("Raw payload: %s", payload)

            data = json.loads(payload)
            logger.debug("Parsed notification data: %s", data)

            station_name = data.get("station_name")
            logger.debug("Station name from notification: %s", station_name)

            if station_name:
                # Use Pydantic model for data validation and conversion
                wind_data = WindDataPoint(
                    timestamp=data.get("update_time"),
                    direction=data.get("direction"),
                    speed_kts=data.get("speed_kts"),
                    gust_kts=data.get("gust_kts"),
                ).model_dump()
                logger.info(
                    "📡 Broadcasting wind data to station %s: %s",
                    station_name,
                    wind_data,
                )
                logger.debug(
                    "Active connections for %s: %s",
                    station_name,
                    len(
                        self.websocket_manager.active_connections.get(station_name, [])
                    ),
                )

                await self.websocket_manager.broadcast_to_station(
                    json.dumps({"type": "wind", "data": wind_data}),
                    station_name,
                )

                # Add new observation to cache
                data_tuple = (
                    wind_data["timestamp"],
                    wind_data["direction"],
                    wind_data["speed_kts"],
                    wind_data["gust_kts"],
                )
                await self.cache_backend.add_observation(station_name, data_tuple)
            else:
                logger.warning("No station name found in notification data")
        except Exception as e:
            logger.error("Error handling notification: %s", e, exc_info=True)

    async def _handle_scraper_status_notification(
        self, connection, pid, channel, payload
    ):
        """Handle scraper status update notifications."""
        try:
            logger.debug(
                "Received scraper status notification from PID %s on channel '%s'",
                pid,
                channel,
            )
            logger.debug("Raw payload: %s", payload)

            if self.watchdog_service:
                # Parse the JSON payload and convert to ScraperStatus model
                data = json.loads(payload)
                logger.debug("Parsed notification data: %s", data)

                # Handle double-encoded JSON strings (in case payload was string-encoded)
                if isinstance(data, str):
                    data = json.loads(data)
                    logger.debug("Re-parsed double-encoded JSON data: %s", data)

                # Ensure we have a dictionary
                if not isinstance(data, dict):
                    logger.error("Expected dict but got %s: %s", type(data), data)
                    return

                # Compute time durations if missing from notification data
                if "time_since_last_attempt" not in data and "last_attempt" in data:
                    try:
                        last_attempt = datetime.fromisoformat(
                            data["last_attempt"].replace("Z", "+00:00")
                        )
                        now = datetime.now(UTC)
                        data["time_since_last_attempt"] = now - last_attempt
                    except Exception as e:
                        logger.warning(
                            "Failed to compute time_since_last_attempt: %s", e
                        )
                        data["time_since_last_attempt"] = None

                if (
                    "time_since_last_success" not in data
                    and "last_success" in data
                    and data["last_success"]
                ):
                    try:
                        last_success = datetime.fromisoformat(
                            data["last_success"].replace("Z", "+00:00")
                        )
                        now = datetime.now(UTC)
                        data["time_since_last_success"] = now - last_success
                    except Exception as e:
                        logger.warning(
                            "Failed to compute time_since_last_success: %s", e
                        )
                        data["time_since_last_success"] = None

                # Create ScraperStatus from the notification data
                scraper_status = ScraperStatus(**data)
                logger.debug("Created ScraperStatus model: %s", scraper_status)

                await self.watchdog_service.handle_scraper_status_update(scraper_status)
            else:
                logger.warning(
                    "Watchdog service not available for scraper status update"
                )

        except Exception as e:
            logger.error(
                "Error handling scraper status notification: %s", e, exc_info=True
            )
