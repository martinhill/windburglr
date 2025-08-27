import asyncio
import logging
from bisect import bisect_left, bisect_right
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple, Any, Set

from .abc import CacheBackend

logger = logging.getLogger("windburglr.cache")


class MemoryCacheBackend(CacheBackend):
    """In-memory cache backend for wind data."""

    def __init__(self, cache_duration_hours: int = 48):
        self.wind_data_cache: Dict[str, List[Tuple[float, int, int, int]]] = {}
        self.cache_oldest_time: Dict[str, float] = {}
        self.cache_lock = asyncio.Lock()
        self.cache_hit_count = 0
        self.cache_miss_count = 0
        self.cache_duration = timedelta(hours=cache_duration_hours)

    async def is_cache_hit(self, station: str, start_time: datetime) -> bool:
        """Check if cache covers the requested time range."""
        if station not in self.cache_oldest_time or station not in self.wind_data_cache:
            return False

        # Convert time to UTC if needed
        if start_time.tzinfo is not None:
            start_time = start_time.astimezone(timezone.utc)

        start_ts = start_time.timestamp()
        oldest_ts = self.cache_oldest_time[station]

        # Quick check: requested range must be within cached range
        if start_ts < oldest_ts:
            logger.debug(
                "Cache miss: start_time %s is before oldest cached time", start_time
            )
            return False

        cache_data = self.wind_data_cache[station]
        if not cache_data:
            return False

        # Check if there's any overlap between requested range and cached range
        newest_ts = cache_data[-1][0]  # Last item has the newest timestamp

        # Check request vs cached range
        within_bounds = oldest_ts <= start_ts <= newest_ts

        if not within_bounds:
            logger.debug(
                "Cache miss: requested range %s, cached range %s to %s",
                start_ts,
                oldest_ts,
                newest_ts,
            )
            return False

        logger.debug(
            "Cache hit: requested range %s, cached range %s to %s",
            start_ts,
            oldest_ts,
            newest_ts,
        )
        return True

    async def get_cached_data(
        self, station: str, start_time: datetime, end_time: datetime
    ) -> List[Tuple[float, int, int, int]]:
        """Get cached data for the specified time range."""
        if station not in self.wind_data_cache:
            return []

        cache_data = self.wind_data_cache[station]
        if not cache_data:
            return []

        # Convert times to UTC timestamps
        if start_time.tzinfo is not None:
            start_time = start_time.astimezone(timezone.utc)
        if end_time.tzinfo is not None:
            end_time = end_time.astimezone(timezone.utc)

        start_ts = start_time.timestamp()
        end_ts = end_time.timestamp()

        # Find data in range using binary search
        timestamps = [item[0] for item in cache_data]
        start_idx = bisect_left(timestamps, start_ts)
        end_idx = bisect_right(timestamps, end_ts)

        return cache_data[start_idx:end_idx]

    async def add_observation(
        self, station: str, data_tuple: Tuple[float, int, int, int]
    ) -> None:
        """Add new observation to cache."""
        async with self.cache_lock:
            if station not in self.wind_data_cache:
                self.wind_data_cache[station] = []
                self.cache_oldest_time[station] = data_tuple[
                    0
                ]  # timestamp is first element

            # Add new data point
            self.wind_data_cache[station].append(data_tuple)

            # Update oldest time if this is the oldest
            if data_tuple[0] < self.cache_oldest_time[station]:
                self.cache_oldest_time[station] = data_tuple[0]

            # Prune old data beyond cache duration
            await self._prune_cache(station)

            logger.debug(
                "Added data to cache for station %s, cache size: %d",
                station,
                len(self.wind_data_cache[station]),
            )

    async def update_cache(
        self,
        station: str,
        start_time: datetime,
        end_time: datetime,
        wind_data: List[Tuple[float, int, int, int]],
    ) -> None:
        """Populate cache with data from database."""
        try:
            # Abort if end_time is before oldest data in cache
            oldest_update_time = self.cache_oldest_time.get(station, 0)
            if end_time.timestamp() < oldest_update_time:
                logger.debug("End time %s is before oldest data in cache", end_time)
                return

            # Sort new data by timestamp to maintain chronological order
            sorted_new_data = sorted(wind_data, key=lambda x: x[0])

            async with self.cache_lock:
                if station not in self.wind_data_cache:
                    self.wind_data_cache[station] = []
                    self.cache_oldest_time[station] = (
                        sorted_new_data[0][0] if sorted_new_data else 0
                    )

                # Get existing cache data
                existing_data = self.wind_data_cache[station]

                # Combine existing and new data, then sort and deduplicate
                combined_data = existing_data + sorted_new_data
                if combined_data:
                    # Sort by timestamp
                    combined_data.sort(key=lambda x: x[0])

                    # Remove duplicates based on timestamp
                    deduplicated_data: List[Tuple[float, int, int, int]] = []
                    seen_timestamps: Set[float] = set()

                    # Iterate in reverse to keep the most recent data for duplicate timestamps
                    for item in reversed(combined_data):
                        timestamp = item[0]
                        if timestamp not in seen_timestamps:
                            seen_timestamps.add(timestamp)
                            deduplicated_data.append(item)

                    # Reverse back to chronological order
                    deduplicated_data.reverse()

                    # Update cache with deduplicated data
                    self.wind_data_cache[station] = deduplicated_data

                    # Update oldest time based on the earliest timestamp in the cache
                    if deduplicated_data:
                        start_ts = start_time.timestamp()
                        self.cache_oldest_time[station] = min(
                            deduplicated_data[0][0], start_ts
                        )
                    else:
                        # No data left, remove station from cache
                        del self.wind_data_cache[station]
                        del self.cache_oldest_time[station]
                else:
                    # No data at all, ensure station is removed from cache
                    if station in self.wind_data_cache:
                        del self.wind_data_cache[station]
                    if station in self.cache_oldest_time:
                        del self.cache_oldest_time[station]

                # Prune old data after adding new data
                await self._prune_cache(station)

            logger.debug(
                "Updated cache for station %s with %s new entries, cache size: %s",
                station,
                len(sorted_new_data),
                len(self.wind_data_cache.get(station, [])),
            )
        except Exception as e:
            logger.error(
                "Error updating cache from database for station %s: %s", station, e
            )

    async def get_cache_stats(self) -> Dict[str, Any]:
        """Return cache statistics."""
        total_entries = sum(len(entries) for entries in self.wind_data_cache.values())
        oldest_entry = None
        if self.cache_oldest_time.values():
            oldest_timestamp = min(self.cache_oldest_time.values())
            oldest_entry = datetime.fromtimestamp(oldest_timestamp, tz=timezone.utc)

        hit_rate = 0.0
        total_requests = self.cache_hit_count + self.cache_miss_count
        if total_requests > 0:
            hit_rate = self.cache_hit_count / total_requests

        return {
            "cache_hit_count": self.cache_hit_count,
            "cache_miss_count": self.cache_miss_count,
            "cache_hit_ratio": hit_rate,
            "stations_cached": len(self.wind_data_cache),
            "total_cached_entries": total_entries,
            "oldest_cache_entry": oldest_entry,
        }

    async def cleanup(self) -> None:
        """Cleanup resources and connections."""
        # Memory backend doesn't need explicit cleanup
        pass

    async def _prune_cache(self, station: str) -> None:
        """Remove data older than cache duration."""
        if station not in self.wind_data_cache:
            return

        cutoff_time = datetime.now(timezone.utc) - self.cache_duration
        cutoff_timestamp = cutoff_time.timestamp()

        # Find insertion point for cutoff time (data is sorted by timestamp)
        cache_data = self.wind_data_cache[station]
        if not cache_data:
            return

        insert_point = bisect_left([item[0] for item in cache_data], cutoff_timestamp)

        if insert_point > 0:
            # Remove old data
            self.wind_data_cache[station] = cache_data[insert_point:]
            if self.wind_data_cache[station]:
                self.cache_oldest_time[station] = self.wind_data_cache[station][0][0]
            else:
                # No data left, remove station from cache
                del self.wind_data_cache[station]
                del self.cache_oldest_time[station]

            logger.debug(
                "Pruned cache for station %s, removed %d old entries",
                station,
                insert_point,
            )
