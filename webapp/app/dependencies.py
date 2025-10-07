"""
Dependency providers for FastAPI application.
Manages application state and provides dependencies to routes.
"""

import glob
import logging
import os
from typing import Annotated

import asyncpg
from fastapi import Depends

from . import config
from .cache.abc import CacheBackend
from .cache.factory import create_cache_from_config
from .services.notifications import PostgresNotificationManager
from .services.station import StationService
from .services.watchdog import WatchdogService
from .services.websocket import WebSocketManager
from .services.wind_data import WindDataService

logger = logging.getLogger("windburglr.dependencies")

_cache_backend: CacheBackend | None = None
_db_pool: asyncpg.Pool | None = None
_websocket_manager: WebSocketManager | None = None
_pg_manager: PostgresNotificationManager | None = None
_wind_service: WindDataService | None = None
_watchdog_service: WatchdogService | None = None
_station_service: StationService | None = None


def reset_dependencies() -> None:
    """Reset all dependencies to their initial state. Mainly used for testing."""
    global \
        _cache_backend, \
        _db_pool, \
        _websocket_manager, \
        _pg_manager, \
        _wind_service, \
        _watchdog_service, \
        _station_service
    _cache_backend = None
    _db_pool = None
    _websocket_manager = None
    _pg_manager = None
    _wind_service = None
    _watchdog_service = None
    _station_service = None


def set_db_pool(pool: asyncpg.Pool) -> None:
    global _db_pool
    _db_pool = pool


async def get_cache_backend() -> CacheBackend:
    global _cache_backend
    if _cache_backend is None:
        _cache_backend = create_cache_from_config(config.get_cache_config())
    return _cache_backend


async def get_db_pool(raise_error: bool = True) -> asyncpg.Pool | None:
    if _db_pool is None and raise_error:
        raise RuntimeError("Database pool not initialized")
    return _db_pool


async def get_websocket_config() -> dict[str, float]:
    """Get WebSocket configuration."""
    return {
        "ping_timeout": config.WEBSOCKET_PING_TIMEOUT,
        "postgres_monitor_interval": config.POSTGRES_MONITOR_INTERVAL,
    }


async def get_websocket_manager() -> WebSocketManager:
    global _websocket_manager
    if _websocket_manager is None:
        _websocket_manager = WebSocketManager()
    return _websocket_manager


async def get_watchdog_service() -> WatchdogService:
    global _watchdog_service
    if _watchdog_service is None:
        _watchdog_service = WatchdogService(
            scraper_status_timeout_minutes=config.SCRAPER_STATUS_TIMEOUT_MINUTES,
        )
    return _watchdog_service


async def get_wind_service(
    cache_backend: Annotated[CacheBackend, Depends(get_cache_backend)],
    pool: Annotated[asyncpg.Pool, Depends(get_db_pool)],
) -> WindDataService:
    global _wind_service
    if _wind_service is None:
        logger.debug("Creating WindDataService pool=%s", pool)
        _wind_service = WindDataService(cache_backend=cache_backend, pool=pool)
    return _wind_service


async def get_pg_connection() -> asyncpg.Connection | None:
    """Get PostgreSQL connection for notifications listener. Override in tests."""
    database_url = config.get_database_url(False)
    if not database_url:
        logger.warning("No database URL configured, skipping Postgres listener")
        return

    try:
        # Create separate connection for notifications
        logger.info(
            "Connecting to Postgres for notifications: %s...",
            database_url[:50],
        )
        return await asyncpg.connect(database_url)
    except Exception as e:
        logger.error("Failed to create Postgres connection: %s", e, exc_info=True)
        return


async def get_pg_manager(
    pg_connection: Annotated[asyncpg.Connection | None, Depends(get_pg_connection)],
    cache_backend: Annotated[CacheBackend, Depends(get_cache_backend)],
    watchdog_service: Annotated[WatchdogService, Depends(get_watchdog_service)],
    websocket_config: Annotated[dict[str, float], Depends(get_websocket_config)],
) -> PostgresNotificationManager:
    global _pg_manager
    if _pg_manager is None:
        websocket_manager = await get_websocket_manager()
        _pg_manager = PostgresNotificationManager(
            cache_backend=cache_backend,
            websocket_manager=websocket_manager,
            watchdog_service=watchdog_service,
            postgres_monitor_interval=websocket_config['postgres_monitor_interval'],
        )
        if pg_connection:
            _pg_manager.set_pg_listener(pg_connection)
            await _pg_manager.start_pg_listener()
    return _pg_manager


def get_station_service(
    pool: Annotated[asyncpg.Pool, Depends(get_db_pool)],
    ) -> StationService:
    global _station_service
    if _station_service is None:
        _station_service = StationService(pool)
    return _station_service


def get_dist_js_files() -> list[str]:
    """Get list of JS filenames in dist/js directory."""
    js_files = glob.glob("dist/js/main-*.js")
    return [os.path.basename(f) for f in js_files]


def get_dist_css_files() -> list[str]:
    """Get list of CSS filenames in dist/css directory."""
    css_files = glob.glob("dist/css/main-*.css")
    return [os.path.basename(f) for f in css_files]
