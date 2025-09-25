import asyncio
import logging

import asyncpg

from .config import Config, StationConfig
from .models import DuplicateObservationError, WindObs

logger = logging.getLogger(__name__)


class DatabaseHandler:
    pool: asyncpg.Pool

    def __init__(self, conf: Config):
        self.config = conf

    async def __aenter__(self):
        self.pool = await asyncpg.create_pool(self.config.db_url)
        for station_config in self.config.stations:
            await self.initialize_station(station_config)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        logger.debug("Updating station status (stopped)")
        try:
            for station_config in self.config.stations:
                await self.update_scraper_status(station_config.name, "stopped")
        except Exception as e:
            logger.error("Error updating station status: %s", e)

        logger.debug("Closing database connection pool")
        try:
            await asyncio.wait_for(self.pool.close(), timeout=5)
        except Exception as e:
            logger.error("Error closing database pool: %s", e)

    async def initialize_station(self, station_config: StationConfig):
        """Initialize a station in the database"""
        async with self.pool.acquire() as conn:
            logger.debug("Initializing station %s", station_config.name)
            await conn.execute(
                """
                INSERT INTO station (name, timezone)
                VALUES ($1, $2)
                ON CONFLICT (name) DO UPDATE SET timezone = EXCLUDED.timezone
                """,
                station_config.name,
                str(station_config.local_timezone),
            )

    async def execute_with_retry(self, query: str, *args, max_retries: int = 5, initial_delay: float = 0.1) -> str:
        for attempt in range(max_retries):
            try:
                async with self.pool.acquire() as connection:
                    return await connection.execute(query, *args)
            except asyncpg.exceptions.ConnectionDoesNotExistError as e:
                logger.warning("ConnectionDoesNotExistError caught on attempt %s: %s", attempt + 1, e)
                if attempt < max_retries - 1:
                    delay = initial_delay * (2 ** attempt)
                    logger.info(f"Retrying in {delay:.2f} seconds...")
                    await asyncio.sleep(delay)
                else:
                    logger.error("Max retries reached. Raising exception.")
                    raise # Re-raise the exception if retries are exhausted

    async def insert_obs(self, obs: WindObs):
        """Insert an observation to the database"""
        try:
            await self.execute_with_retry(
                """
                INSERT INTO wind_obs (station_id, direction, speed_kts, gust_kts, update_time)
                VALUES (
                    (SELECT id FROM station WHERE name = $1),
                    $2, $3, $4, $5
                )
                """,
                obs.station,
                obs.direction,
                obs.speed,
                obs.gust,
                obs.timestamp,
            )
        except asyncpg.exceptions.UniqueViolationError as e:
            raise DuplicateObservationError(
                f"Observation already exists: {obs}"
            ) from e

    async def update_scraper_status(
        self, station: str, status: str, error_message: str | None = None
    ):
        """Update scraper status in the database"""
        try:
            await self.execute_with_retry(
                "SELECT update_scraper_status($1, $2, $3)",
                station,
                status,
                error_message,
            )
        except Exception as e:
            # Don't let status update failures break the main scraping logic
            logger.error("Failed to update scraper status for %s: %s", station, e)


# Output handlers
async def handle_postgres(obs: WindObs, db_handler: DatabaseHandler):
    await db_handler.insert_obs(obs)
    logger.info("Inserted: %s", obs)


# Status handler
async def handle_status_postgres(
    station: str, status: str, error_message: str | None, db_handler: DatabaseHandler
):
    await db_handler.update_scraper_status(station, status, error_message)
