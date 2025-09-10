"""
Dependency providers for FastAPI application.
Manages application state and provides dependencies to routes.
"""

import asyncio
import glob
import logging
import os

import asyncpg

from .cache.abc import CacheBackend
from .config import ACQUIRE_CONNECTION_TIMEOUT
from .database import create_db_pool
from .services.notifications import PostgresNotificationManager
from .services.websocket import WebSocketManager
from .services.wind_data import WindDataService

logger = logging.getLogger("windburglr.dependencies")

# Application state - initialized during startup
_cache_backend: CacheBackend | None = None
_db_pool: asyncpg.Pool | None = None
_websocket_manager: WebSocketManager | None = None
_pg_manager: PostgresNotificationManager | None = None
_wind_service: WindDataService | None = None


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


async def get_db_pool(raise_error: bool = True) -> asyncpg.Pool:
    """Get the database pool instance."""
    if _db_pool is None and raise_error:
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


async def get_db_connection() -> asyncpg.Connection:
    """Get a database connection with automatic recovery and error handling."""
    pool = await get_db_pool()

    try:
        # Try to acquire connection
        async with pool.acquire(timeout=ACQUIRE_CONNECTION_TIMEOUT) as conn:
            yield conn

    except (asyncpg.exceptions.InterfaceError, asyncpg.exceptions.ConnectionDoesNotExistError) as e:
        logger.warning("Database connection failed, attempting pool recreation: %s", e)

        # Gracefully wait for existing connections to close
        try:
            await asyncio.wait_for(pool.close(), timeout=5)
        except TimeoutError:
            logger.warning("Timed out waiting for database connection pool to close")
        except Exception as close_error:
            logger.error("Error closing database connection pool: %s", close_error)

        # Try to recreate the pool
        try:
            new_pool = await create_db_pool()
            set_db_pool(new_pool)  # Update global pool reference
            pool = new_pool
            async with pool.acquire(timeout=ACQUIRE_CONNECTION_TIMEOUT) as conn:
                await conn.fetchval("SELECT 1")
                yield conn
        except Exception as recreate_error:
            logger.error("Failed to recreate database pool: %s", recreate_error)
            raise RuntimeError("Database connection unavailable") from recreate_error

    except Exception as e:
        logger.error("Unexpected database connection error: %s", e)
        raise


def get_dist_js_files() -> list[str]:
    """Get list of JS filenames in dist/js directory."""
    js_files = glob.glob("dist/js/main-*.js")
    return [os.path.basename(f) for f in js_files]


def get_dist_css_files() -> list[str]:
    """Get list of CSS filenames in dist/css directory."""
    css_files = glob.glob("dist/css/main-*.css")
    return [os.path.basename(f) for f in css_files]
