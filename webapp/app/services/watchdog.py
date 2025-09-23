import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import asyncpg

from app.models import ScraperStatus

logger = logging.getLogger("windburglr.watchdog")


class WatchdogService:
    """Maintains current status of upstream scraper services."""

    def __init__(self, scraper_status_timeout_minutes: int = 5):
        self.scraper_status: Dict[str, ScraperStatus] = {}
        self.websocket_manager = None
        self.staleness_threshold = timedelta(minutes=scraper_status_timeout_minutes)

    async def initialize(self, pg_connection: asyncpg.Connection):
        """Initialize the watchdog service by querying current scraper status using provided connection."""
        try:
            logger.info(
                "Initializing watchdog service with existing database connection"
            )

            # Query initial scraper status
            await self._load_initial_scraper_status(pg_connection)

        except Exception as e:
            logger.error("Failed to initialize watchdog service: %s", e, exc_info=True)

    async def _load_initial_scraper_status(self, pg_connection: asyncpg.Connection):
        """Load initial scraper status from database function."""
        try:
            # Call the get_scraper_status function - it returns table rows, not JSON
            rows = await pg_connection.fetch(
                """
                SELECT
                    station_name,
                    last_success,
                    last_attempt,
                    status,
                    error_message,
                    retry_count,
                    time_since_last_attempt,
                    time_since_last_success
                FROM get_scraper_status()
                """
            )

            if rows:
                # Store as a dictionary of ScraperStatus models keyed by station_name
                self.scraper_status = {}
                for row in rows:
                    # PostgreSQL INTERVAL is automatically converted to timedelta by asyncpg
                    # Pydantic handles timedelta natively, no manual conversion needed
                    status = ScraperStatus(**row)
                    self.scraper_status[status.station_name] = status

                logger.info(
                    "Loaded initial scraper status for %d stations",
                    len(self.scraper_status),
                )
            else:
                logger.warning("No scraper status data returned from database")
                self.scraper_status = {}

        except Exception as e:
            logger.error("Failed to load initial scraper status: %s", e, exc_info=True)

    async def check_and_update_stale_statuses(self):
        """Check and update statuses for stations that may be have stopped providing status updates."""
        logger.debug("Checking for stale stations...")
        now = datetime.now(timezone.utc)
        stale_stations = [
            status.model_copy()
            for status in self.scraper_status.values()
            if status.last_attempt
            and (now - status.last_attempt) > self.staleness_threshold
            and status.status == "healthy"
        ]

        for status in stale_stations:
            logger.info("Detected stale station: %s", status.station_name)
            status.status = "suspended"
            status.error_message = "No recent status update"
            await self.handle_scraper_status_update(status)

    def set_websocket_manager(self, websocket_manager):
        """Set the websocket manager for sending status updates."""
        self.websocket_manager = websocket_manager

    async def handle_scraper_status_update(self, current_status: ScraperStatus):
        """Handle scraper status update notifications."""
        try:
            logger.debug("Received scraper status update: %s", current_status)

            # Store the previous status to detect changes
            previous_status = self.get_station_status_by_name(
                current_status.station_name
            )

            # Check if status field changed or is new, and notify via websocket
            should_send_update = False

            if previous_status is None:
                # New station status - always send update
                logger.info(
                    "New station status for %s: %s",
                    current_status.station_name,
                    current_status.status,
                )
                should_send_update = True
            elif current_status and (
                previous_status.status != current_status.status
                or previous_status.retry_count != current_status.retry_count
            ):
                # Status changed - send update
                logger.info(
                    "Status changed for station %s: %s -> %s",
                    current_status.station_name,
                    previous_status.status,
                    current_status.status,
                )
                should_send_update = True

            # Update the internal status directly with the ScraperStatus object
            await self._update_station_status_with_model(current_status)

            # Send websocket update if needed
            if should_send_update and self.websocket_manager:
                await self.websocket_manager.send_station_status_update(
                    current_status.station_name, self
                )

            logger.info(
                "Processed scraper status update notification: %s", current_status
            )

        except Exception as e:
            logger.error("Error handling scraper status update: %s", e, exc_info=True)

    async def _update_station_status_with_model(self, scraper_status: ScraperStatus):
        """Update the status for a specific station using a ScraperStatus model."""
        station_name = scraper_status.station_name
        if not station_name:
            logger.warning("No station_name in ScraperStatus: %s", scraper_status)
            return

        # Store the ScraperStatus model directly
        self.scraper_status[station_name] = scraper_status
        logger.debug("Updated status for station %s: %s", station_name, scraper_status)

    def get_station_status_by_name(self, station_name: str) -> ScraperStatus | None:
        """Get status for a specific station by name."""
        if not station_name or not self.scraper_status:
            return None

        return self.scraper_status.get(station_name)

    def get_scraper_status(self) -> List[ScraperStatus]:
        """Get current scraper status as a list."""
        return list(self.scraper_status.values())

    def cleanup(self):
        """Cleanup watchdog service - no database connection to close since we use shared connection."""
        logger.info("Watchdog service cleanup completed")
