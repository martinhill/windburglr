import asyncio
import contextlib
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg

from .wind_data import WindDataService

logger = logging.getLogger("windburglr.cache_hydration")


class CacheHydrator:
    """Prefills the wind data cache in the background.

    Loads the last `hours` of observations for the default station and every station
    the scraper has updated within that window, so the first page loads after startup
    (or after a resume) are served from memory. Requests arriving meanwhile miss the
    cache and query the database as usual; both paths write through the cache's
    lock-protected, de-duplicating merge, so they can overlap safely.
    """

    def __init__(
        self,
        wind_service: WindDataService,
        pool: asyncpg.Pool,
        hours: int,
        default_station: str,
    ):
        self.wind_service = wind_service
        self.pool = pool
        self.hours = hours
        self.default_station = default_station
        self.task: asyncio.Task[None] | None = None
        self.last_run: dict[str, Any] = {
            "state": "disabled" if hours <= 0 else "pending"
        }

    def start(self) -> asyncio.Task[None] | None:
        """Start a hydration run, replacing one still in progress.

        A run started earlier may have read data from before a staleness mark, so it
        is cancelled rather than left to clear the mark with old data.
        """
        if self.hours <= 0:
            return None
        if self.task and not self.task.done():
            self.task.cancel()
        self.task = asyncio.create_task(self._run(), name="cache-hydration")
        return self.task

    async def stop(self) -> None:
        if self.task and not self.task.done():
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task

    async def _run(self) -> None:
        started = time.monotonic()
        end_time = datetime.now(UTC)
        start_time = end_time - timedelta(hours=self.hours)
        self.last_run = {"state": "running", "started_at": end_time.isoformat()}
        try:
            stations = await self._stations_to_hydrate(start_time)
            logger.info(
                "Hydrating cache: %d hours for %s", self.hours, ", ".join(stations)
            )
            observations = 0
            hydrated: list[str] = []
            for station in stations:
                try:
                    observations += await self.wind_service.prefill_cache(
                        station, start_time, end_time
                    )
                    hydrated.append(station)
                except Exception as e:
                    logger.error(
                        "Cache hydration failed for station %s: %s", station, e
                    )
            duration = time.monotonic() - started
            self.last_run = {
                "state": "done",
                "started_at": end_time.isoformat(),
                "stations": hydrated,
                "observations": observations,
                "duration_seconds": round(duration, 3),
            }
            logger.info(
                "Cache hydrated: %d observations for %d stations in %.2fs",
                observations,
                len(hydrated),
                duration,
            )
        except asyncio.CancelledError:
            self.last_run = {"state": "cancelled", "started_at": end_time.isoformat()}
            logger.info("Cache hydration cancelled")
            raise
        except Exception as e:
            self.last_run = {"state": "failed", "started_at": end_time.isoformat()}
            logger.error("Cache hydration failed: %s", e, exc_info=True)

    async def _stations_to_hydrate(self, since: datetime) -> list[str]:
        """The default station, then any station the scraper updated since `since`."""
        stations = [self.default_station]
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT station_name FROM get_scraper_status() WHERE last_success >= $1",
                    since,
                )
        except Exception as e:
            logger.warning("Could not list scraped stations for hydration: %s", e)
            return stations
        stations.extend(
            row["station_name"] for row in rows if row["station_name"] not in stations
        )
        return stations
