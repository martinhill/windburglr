"""
Dependency providers for FastAPI routes.

The services are created once at startup by the lifespan (`app/lifespan.py`) and kept on
`app.state`; these providers hand them to routes. `HTTPConnection` covers both HTTP
requests and WebSockets.
"""

import glob
import os

import asyncpg
from starlette.requests import HTTPConnection

from .cache.abc import CacheBackend
from .services.cache_hydration import CacheHydrator
from .services.notifications import PostgresNotificationManager
from .services.station import StationService
from .services.watchdog import WatchdogService
from .services.websocket import WebSocketManager
from .services.wind_data import WindDataService


async def get_db_pool(conn: HTTPConnection) -> asyncpg.Pool:
    return conn.app.state.db_pool


async def get_cache_backend(conn: HTTPConnection) -> CacheBackend:
    return conn.app.state.cache_backend


async def get_websocket_ping_timeout(conn: HTTPConnection) -> float:
    return conn.app.state.websocket_ping_timeout


async def get_websocket_manager(conn: HTTPConnection) -> WebSocketManager:
    return conn.app.state.websocket_manager


async def get_watchdog_service(conn: HTTPConnection) -> WatchdogService:
    return conn.app.state.watchdog_service


async def get_wind_service(conn: HTTPConnection) -> WindDataService:
    return conn.app.state.wind_service


async def get_pg_manager(conn: HTTPConnection) -> PostgresNotificationManager:
    return conn.app.state.pg_manager


async def get_station_service(conn: HTTPConnection) -> StationService:
    return conn.app.state.station_service


async def get_cache_hydrator(conn: HTTPConnection) -> CacheHydrator:
    return conn.app.state.cache_hydrator


def get_dist_js_files() -> list[str]:
    """Get list of JS filenames in dist/js directory."""
    js_files = glob.glob("dist/js/main-*.js")
    return [os.path.basename(f) for f in js_files]


def get_dist_css_files() -> list[str]:
    """Get list of CSS filenames in dist/css directory."""
    css_files = glob.glob("dist/css/main-*.css")
    return [os.path.basename(f) for f in css_files]
