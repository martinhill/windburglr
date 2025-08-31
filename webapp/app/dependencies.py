"""
Dependency providers for FastAPI application.
Manages application state and provides dependencies to routes.
"""

import os
import glob
from typing import List, Optional

import asyncpg

from .cache.abc import CacheBackend
from .services.websocket import WebSocketManager
from .services.notifications import PostgresNotificationManager
from .services.wind_data import WindDataService

# Application state - initialized during startup
_cache_backend: Optional[CacheBackend] = None
_db_pool: Optional[asyncpg.Pool] = None
_websocket_manager: Optional[WebSocketManager] = None
_pg_manager: Optional[PostgresNotificationManager] = None
_wind_service: Optional[WindDataService] = None


# Initialization functions (called from lifespan)
def set_cache_backend(cache_backend: CacheBackend) -> None:
    global _cache_backend
    _cache_backend = cache_backend


def set_db_pool(pool: asyncpg.Pool) -> None:
    global _db_pool
    _db_pool = pool


def set_websocket_manager(manager: WebSocketManager) -> None:
    global _websocket_manager
    _websocket_manager = manager


def set_pg_manager(manager: PostgresNotificationManager) -> None:
    global _pg_manager
    _pg_manager = manager


def set_wind_service(service: WindDataService) -> None:
    global _wind_service
    _wind_service = service


# FastAPI dependency functions
async def get_cache_backend() -> CacheBackend:
    """Get the cache backend instance."""
    if _cache_backend is None:
        raise RuntimeError("Cache backend not initialized")
    return _cache_backend


async def get_db_pool() -> asyncpg.Pool:
    """Get the database pool instance."""
    if _db_pool is None:
        raise RuntimeError("Database pool not initialized")
    return _db_pool


async def get_websocket_manager() -> WebSocketManager:
    """Get the WebSocket manager instance."""
    if _websocket_manager is None:
        raise RuntimeError("WebSocket manager not initialized")
    return _websocket_manager


async def get_pg_manager() -> PostgresNotificationManager:
    """Get the PostgreSQL notification manager instance."""
    if _pg_manager is None:
        raise RuntimeError("PostgreSQL manager not initialized")
    return _pg_manager


async def get_wind_service() -> WindDataService:
    """Get the wind data service instance."""
    if _wind_service is None:
        raise RuntimeError("Wind service not initialized")
    return _wind_service


def get_dist_js_files() -> List[str]:
    """Get list of JS filenames in dist/js directory."""
    js_files = glob.glob("dist/js/main-*.js")
    return [os.path.basename(f) for f in js_files]
