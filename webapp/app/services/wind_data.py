import logging
from collections.abc import Generator
from datetime import UTC, datetime
from typing import Any

import asyncpg

from ..cache.abc import CacheBackend
from ..models import WindDataPoint

logger = logging.getLogger("windburglr.wind_data")


class WindDataService:
    """Service for managing wind data operations."""

    def __init__(self, cache_backend: CacheBackend):
        self.cache = cache_backend

    async def query_wind_data(
        self,
        station: str,
        start_time: datetime,
        end_time: datetime,
        conn: asyncpg.Connection,
    ) -> Generator[WindDataPoint]:
        """Query wind data from database for a station and time range."""
        # Convert timezone-aware datetimes to timezone-naive UTC for asyncpg
        if start_time.tzinfo is not None:
            start_time = start_time.astimezone(UTC).replace(tzinfo=None)
        if end_time.tzinfo is not None:
            end_time = end_time.astimezone(UTC).replace(tzinfo=None)

        # Connection is already acquired and tested by the dependency
        rows = await conn.fetch(
            "SELECT * FROM get_wind_data_by_station_range($1, $2, $3)",
            station,
            start_time,
            end_time,
        )
        return (
            WindDataPoint(
                timestamp=row["update_time"],
                direction=row["direction"],
                speed_kts=row["speed_kts"],
                gust_kts=row["gust_kts"],
            )
            for row in rows
        )

    async def get_latest_wind_data(
        self, station: str, conn: asyncpg.Connection
    ) -> dict[str, Any] | None:
        """Get the latest wind observation for a station."""
        # Connection is already acquired and tested by the dependency
        row = await conn.fetchrow(
            "SELECT * FROM get_latest_wind_observation($1)", station
        )
        if row:
            # Ensure update_time is timezone-aware before processing
            return WindDataPoint(
                timestamp=row['update_time'],
                direction=row["direction"],
                speed_kts=row["speed_kts"],
                gust_kts=row["gust_kts"],
            ).model_dump()
        return None

    async def get_cached_or_fresh_data(
        self,
        station: str,
        start_time: datetime,
        end_time: datetime,
        conn: asyncpg.Connection,
    ) -> dict[str, Any]:
        """Get wind data from cache if available, otherwise query database."""
        # Try cache-first approach
        is_cache_hit = await self.cache.is_cache_hit(station, start_time)
        logger.debug(
            "Cache check for station %s: hit=%s, start_time=%s",
            station,
            is_cache_hit,
            start_time,
        )

        if is_cache_hit:
            # Cache hit - get data from cache
            cached_data = await self.cache.get_cached_data(
                station, start_time, end_time
            )
            self.cache.cache_hit_count += 1
            logger.debug(
                "Cache hit for station %s, returned %s data points",
                station,
                len(cached_data),
            )
            winddata = cached_data
        else:
            # Cache miss - query database and update cache
            self.cache.cache_miss_count += 1
            logger.debug("Cache miss for station %s, querying database", station)

            # Query database
            winddata = [
                (point.timestamp, point.direction, point.speed_kts, point.gust_kts)
                for point in await self.query_wind_data(
                    station, start_time, end_time, conn
                )
            ]

            # Update cache with fresh data
            logger.debug(
                "Updating cache for station %s with data from %s to %s",
                station,
                start_time,
                end_time,
            )
            await self.cache.update_cache(station, start_time, end_time, winddata)

        return {
            "winddata": winddata,
            "cache_hit": is_cache_hit,
        }
