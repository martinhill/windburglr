import logging
from async_lru import alru_cache

import asyncpg

logger = logging.getLogger("windburglr.station")


@alru_cache(maxsize=10)
async def get_station_timezone(station_name: str, pool: asyncpg.Pool) -> str:
    """Get the timezone for a given station."""
    async with pool.acquire() as conn:
        result = await conn.fetchval(
            "SELECT get_station_timezone_name($1)", station_name
        )
        logger.debug("get_station_timezone result for %s: %s", station_name, result)
        return result or "UTC"
