from abc import ABC, abstractmethod
from typing import List, Tuple, Dict, Any
from datetime import datetime


class CacheBackend(ABC):
    """Abstract base class for cache backends."""

    @abstractmethod
    async def is_cache_hit(self, station: str, start_time: datetime) -> bool:
        """Check if cache covers the requested time range."""
        pass

    @abstractmethod
    async def get_cached_data(
        self, station: str, start_time: datetime, end_time: datetime
    ) -> List[Tuple[float, int, int, int]]:
        """Retrieve cached data for the specified time range.
        Returns list of (timestamp, direction, speed_kts, gust_kts) tuples.
        """
        pass

    @abstractmethod
    async def add_observation(
        self, station: str, data_tuple: Tuple[float, int, int, int]
    ) -> None:
        """Add a single new observation to the cache."""
        pass

    @abstractmethod
    async def update_cache(
        self,
        station: str,
        start_time: datetime,
        end_time: datetime,
        wind_data: List[Tuple[float, int, int, int]],
    ) -> None:
        """Populate cache with data from database."""
        pass

    @abstractmethod
    async def get_cache_stats(self) -> Dict[str, Any]:
        """Return cache statistics."""
        pass

    @abstractmethod
    async def cleanup(self) -> None:
        """Cleanup resources and connections."""
        pass
