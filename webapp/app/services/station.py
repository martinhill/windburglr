import logging

import asyncpg

logger = logging.getLogger("windburglr.station")


cached_timezones = {}

async def get_station_timezone(station_name: str, pool: asyncpg.Pool) -> str:
    """Get the timezone for a given station."""
    if station_name in cached_timezones:
        return cached_timezones[station_name]

    # Connection is already acquired and tested by the dependency
    async with pool.acquire() as conn:
        result = await conn.fetchval(
            "SELECT get_station_timezone_name($1)", station_name
        )
        logger.debug("get_station_timezone result for %s: %s", station_name, result)

    if result:
        cached_timezones[station_name] = result
    return result or "UTC"
