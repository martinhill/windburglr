import asyncio
import json
import logging

import asyncpg

from ..cache.abc import CacheBackend
from ..config import get_database_url
from ..models import WindDataPoint
from .websocket import WebSocketManager

logger = logging.getLogger("windburglr.notifications")


class PostgresNotificationManager:
    """Manages PostgreSQL LISTEN/NOTIFY connections for real-time updates."""

    def __init__(
        self, cache_backend: CacheBackend, websocket_manager: WebSocketManager
    ):
        self.cache_backend = cache_backend
        self.websocket_manager = websocket_manager
        self.pg_listener: asyncpg.Connection | None = None
        self.notification_count = 0
        self.monitor_task: asyncio.Task | None = None
        self._is_pg_listener_healthy = False

    def set_pg_listener(self, connection: asyncpg.Connection):
        """Inject an asyncpg connection to be used as the pg_listener."""
        self.pg_listener = connection

    async def start_pg_listener(self):
        """Start PostgreSQL listener for real-time notifications."""
        # If a connection was already injected, use it directly
        if self.pg_listener:
            logger.info("Using injected PostgreSQL connection for listener")
        else:
            # Create a new connection if none was injected
            database_url = get_database_url(False)
            if not database_url:
                logger.warning(
                    "No database URL configured, skipping PostgreSQL listener"
                )
                return

            try:
                # Create separate connection for notifications
                logger.info(
                    "Connecting to PostgreSQL for notifications: %s...",
                    database_url[:50],
                )
                self.pg_listener = await asyncpg.connect(database_url)
            except Exception as e:
                logger.error(
                    "Failed to create PostgreSQL connection: %s", e, exc_info=True
                )
                self._is_pg_listener_healthy = False
                return

        try:
            # Test the connection
            if self.pg_listener:
                result = await self.pg_listener.fetchval("SELECT 1")
                logger.debug("PostgreSQL connection test result: %s", result)

                await self.pg_listener.add_listener(
                    "wind_obs_insert", self._handle_notification
                )
            logger.info("PostgreSQL listener started successfully")
            logger.info("Listening for channels: wind_obs_insert")

            # Mark connection as healthy
            self._is_pg_listener_healthy = True

            # Start background monitoring task
            self.monitor_task = asyncio.create_task(self._monitor_pg_connection())
            logger.info("PostgreSQL connection monitoring started")

        except Exception as e:
            logger.error("Failed to start PostgreSQL listener: %s", e, exc_info=True)
            self._is_pg_listener_healthy = False

    async def stop_pg_listener(self):
        """Stop PostgreSQL listener and cleanup resources."""
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
                logger.warning("Monitor task did not cancel within timeout, forcing completion")
            except asyncio.CancelledError:
                logger.info("PostgreSQL connection monitor task cancelled")
            except Exception as e:
                logger.error("Error cancelling monitor task: %s", e)

        if self.pg_listener:
            try:
                logger.debug("Closing PostgreSQL listener...")
                await asyncio.wait_for(self.pg_listener.close(), timeout=5.0)
                logger.info("PostgreSQL listener stopped")
            except TimeoutError:
                logger.warning("PostgreSQL connection close timed out")
            except Exception as e:
                logger.error("Error stopping PostgreSQL listener: %s", e, exc_info=True)

        self._is_pg_listener_healthy = False

    async def _check_pg_connection_health(self) -> bool:
        """Check if PostgreSQL listener connection is healthy."""
        if not self.pg_listener or self.pg_listener.is_closed():
            self._is_pg_listener_healthy = False
            return False

        try:
            # Simple health check query
            await self.pg_listener.fetchval("SELECT 1")
            self._is_pg_listener_healthy = True
            return True
        except Exception as e:
            logger.error("PostgreSQL connection health check failed: %s", e)
            self._is_pg_listener_healthy = False
            return False

    async def _reconnect_pg_listener(self) -> bool:
        """Attempt to reconnect PostgreSQL listener with exponential backoff."""
        max_retries = 5
        base_delay = 1  # Start with 1 second

        for attempt in range(max_retries):
            try:
                logger.info(
                    "Attempting PostgreSQL listener reconnection (attempt %s/%s)",
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

                logger.info("PostgreSQL listener reconnected successfully")
                self._is_pg_listener_healthy = True
                return True

            except Exception as e:
                delay = base_delay * (2**attempt)  # Exponential backoff
                logger.error("Reconnection attempt %s failed: %s", attempt + 1, e)

                if attempt < max_retries - 1:
                    await asyncio.sleep(delay)

        logger.error("Failed to reconnect PostgreSQL listener after all attempts")
        self._is_pg_listener_healthy = False
        return False

    @property
    def is_pg_listener_healthy(self) -> bool:
        """Check if PostgreSQL listener is healthy."""
        return self._is_pg_listener_healthy

    async def _monitor_pg_connection(self):
        """Background task to monitor PostgreSQL connection health."""
        while True:
            try:
                if not await self._check_pg_connection_health():
                    logger.warning(
                        "PostgreSQL listener connection lost, attempting reconnection..."
                    )
                    await self._reconnect_pg_listener()

                # Check every 30 seconds
                await asyncio.sleep(30)
                logger.debug("PostgreSQL connection monitor running")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in PostgreSQL connection monitor: %s", e)
                await asyncio.sleep(5)  # Shorter wait on error

    async def _handle_notification(self, connection, pid, channel, payload):
        """Handle incoming PostgreSQL notifications."""
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
                    json.dumps(wind_data), station_name
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
