import asyncio
import json
import logging
from datetime import UTC, datetime

import asyncpg

from ..cache.abc import CacheBackend
from ..config import get_database_url
from ..models import ScraperStatus, WindDataPoint
from .watchdog import WatchdogService
from .websocket import WebSocketManager

logger = logging.getLogger("windburglr.notifications")


class PostgresNotificationManager:
    """Manages Postgres LISTEN/NOTIFY connections for real-time updates."""

    def __init__(
        self,
        cache_backend: CacheBackend,
        websocket_manager: WebSocketManager,
        watchdog_service: WatchdogService | None = None,
        postgres_monitor_interval: float = 30.0,
    ):
        self.cache_backend = cache_backend
        self.websocket_manager = websocket_manager
        self.watchdog_service = watchdog_service
        self.postgres_monitor_interval = postgres_monitor_interval
        self.pg_listener: asyncpg.Connection | None = None
        self.notification_count = 0
        self.monitor_task: asyncio.Task | None = None
        self._is_pg_listener_healthy = False

    def set_pg_listener(self, connection: asyncpg.Connection):
        """Inject an asyncpg connection to be used as the pg_listener."""
        self.pg_listener = connection

    async def start_pg_listener(self):
        """Start Postgres listener for real-time notifications."""
        # If a connection was already injected, use it directly
        if self.pg_listener:
            logger.info("Using injected Postgres connection for listener")
        else:
            # Create a new connection if none was injected
            database_url = get_database_url(False)
            if not database_url:
                logger.warning("No database URL configured, skipping Postgres listener")
                return

            try:
                # Create separate connection for notifications
                logger.info(
                    "Connecting to Postgres for notifications: %s...",
                    database_url[:50],
                )
                self.pg_listener = await asyncpg.connect(database_url)
            except Exception as e:
                logger.error(
                    "Failed to create Postgres connection: %s", e, exc_info=True
                )
                self._is_pg_listener_healthy = False
                return

        try:
            # Test the connection
            if self.pg_listener:
                result = await self.pg_listener.fetchval("SELECT 1")
                logger.debug("Postgres connection test result: %s", result)

                await self.pg_listener.add_listener(
                    "wind_obs_insert", self._handle_notification
                )
                await self.pg_listener.add_listener(
                    "scraper_status_update", self._handle_scraper_status_notification
                )

                # Initialize watchdog service with this connection
                if self.watchdog_service:
                    await self.watchdog_service.initialize(self.pg_listener)
                    # Set websocket manager for status updates
                    self.watchdog_service.set_websocket_manager(self.websocket_manager)

            logger.info("Postgres listener started successfully")
            logger.info(
                "Listening for channels: wind_obs_insert, scraper_status_update"
            )

            # Mark connection as healthy
            self._is_pg_listener_healthy = True

            # Start background monitoring task
            self.monitor_task = asyncio.create_task(self._monitor_pg_connection())
            logger.info("Postgres connection monitoring started")

        except Exception as e:
            logger.error("Failed to start Postgres listener: %s", e, exc_info=True)
            self._is_pg_listener_healthy = False

    async def stop_pg_listener(self):
        """Stop Postgres listener and cleanup resources."""
        # Cancel monitoring task
        if (
            hasattr(self, "monitor_task")
            and self.monitor_task
            and not self.monitor_task.done()
        ):
            self.monitor_task.cancel()
            try:
                logger.debug("Waiting for monitor task to complete...")
                await asyncio.wait_for(self.monitor_task, timeout=5.0)
            except TimeoutError:
                logger.warning(
                    "Monitor task did not cancel within timeout, forcing completion"
                )
            except asyncio.CancelledError:
                logger.info("Postgres connection monitor task cancelled")
            except Exception as e:
                logger.error("Error cancelling monitor task: %s", e)

        if self.pg_listener:
            try:
                logger.debug("Closing Postgres listener...")
                await asyncio.wait_for(self.pg_listener.close(), timeout=5.0)
                logger.info("Postgres listener stopped")
            except TimeoutError:
                logger.warning("Postgres connection close timed out")
            except Exception as e:
                logger.error("Error stopping Postgres listener: %s", e, exc_info=True)

        self._is_pg_listener_healthy = False

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

    async def _reconnect_pg_listener(self) -> bool:
        """Attempt to reconnect Postgres listener with exponential backoff."""
        max_retries = 5
        base_delay = 1  # Start with 1 second

        for attempt in range(max_retries):
            try:
                logger.info(
                    "Attempting Postgres listener reconnection (attempt %s/%s)",
                    attempt + 1,
                    max_retries,
                )

                # Clean up existing connection
                if self.pg_listener and not self.pg_listener.is_closed():
                    await self.pg_listener.close()

                # Re-establish connection
                database_url = get_database_url(False)
                if not database_url:
                    logger.error("No database URL available for reconnection")
                    return False

                self.pg_listener = await asyncpg.connect(database_url)
                if self.pg_listener:
                    await self.pg_listener.add_listener(
                        "wind_obs_insert", self._handle_notification
                    )
                    await self.pg_listener.add_listener(
                        "scraper_status_update",
                        self._handle_scraper_status_notification,
                    )

                logger.info("Postgres listener reconnected successfully")
                self._is_pg_listener_healthy = True
                return True

            except Exception as e:
                delay = base_delay * (2**attempt)  # Exponential backoff
                logger.error("Reconnection attempt %s failed: %s", attempt + 1, e)

                if attempt < max_retries - 1:
                    await asyncio.sleep(delay)

        logger.error("Failed to reconnect Postgres listener after all attempts")
        self._is_pg_listener_healthy = False
        return False

    @property
    def is_pg_listener_healthy(self) -> bool:
        """Check if Postgres listener is healthy."""
        return self._is_pg_listener_healthy

    async def _monitor_pg_connection(self):
        """Background task to monitor Postgres connection health."""
        while True:
            try:
                if not await self._check_pg_connection_health():
                    logger.warning(
                        "Postgres listener connection lost, attempting reconnection..."
                    )
                    await self._reconnect_pg_listener()

                # In case of scraper process being suspended, scraper status notifications would not be sent.
                # Periodically check for stale statuses
                if self._is_pg_listener_healthy and self.watchdog_service:
                    await self.watchdog_service.check_and_update_stale_statuses()

                # Check at configured interval
                await asyncio.sleep(self.postgres_monitor_interval)
                logger.debug("Postgres connection monitor running")

            except asyncio.CancelledError:
                break
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
