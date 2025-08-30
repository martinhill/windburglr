from typing import Dict, Any

from .abc import CacheBackend
from .memory import MemoryCacheBackend


class CacheFactory:
    """Factory for creating cache backend instances."""

    @staticmethod
    def create_cache(backend: str = "memory", **kwargs: Any) -> CacheBackend:
        """Create a cache backend instance."""
        if backend == "memory":
            return MemoryCacheBackend(**kwargs)
        else:
            raise ValueError(f"Unknown cache backend: {backend}")


def create_cache_from_config(config: Dict[str, Any]) -> CacheBackend:
    """Create cache backend from configuration dictionary."""
    backend_type = config.get("type", "memory")
    options = config.get("options", {})
    return CacheFactory.create_cache(backend_type, **options)
