import logging

import asyncpg

logger = logging.getLogger("windburglr.station")


class StationService:

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.cached_timezones = {}

    async def get_station_timezone(self, station_name: str) -> str:
        """Get the timezone for a given station."""
        if station_name in self.cached_timezones:
            return self.cached_timezones[station_name]

        # Connection is already acquired and tested by the dependency
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT get_station_timezone_name($1)", station_name
            )
            logger.debug("get_station_timezone result for %s: %s", station_name, result)

        if result:
            self.cached_timezones[station_name] = result
        return result or "UTC"
