"""Application lifespan: builds every service once at startup and tears it down in reverse."""

import asyncio
import logging
from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass

import asyncpg
from fastapi import FastAPI

from . import config
from .cache.factory import create_cache_from_config
from .database import connect_listener, create_db_pool
from .services.cache_hydration import CacheHydrator
from .services.notifications import ListenerConnector, PostgresNotificationManager
from .services.station import StationService
from .services.watchdog import WatchdogService
from .services.websocket import WebSocketManager
from .services.wind_data import WindDataService
from .utils.suspension_detector import SuspensionDetector

logger = logging.getLogger("windburglr")


@asynccontextmanager
async def open_db_pool() -> AsyncGenerator[asyncpg.Pool]:
    """Create the query pool and close it on exit."""
    pool = await create_db_pool()
    try:
        yield pool
    finally:
        logger.info("Closing database connection pool...")
        try:
            await asyncio.wait_for(pool.close(), timeout=10.0)
        except TimeoutError:
            logger.warning("Database pool did not close in time, terminating it")
            pool.terminate()
        logger.info("Database connection pool closed")


@dataclass(frozen=True)
class StartupOptions:
    """How the lifespan reaches the database, and tunables; tests substitute these."""

    open_db_pool: Callable[[], AbstractAsyncContextManager[asyncpg.Pool]] = open_db_pool
    connect_listener: ListenerConnector = connect_listener
    websocket_ping_timeout: float = config.WEBSOCKET_PING_TIMEOUT
    postgres_monitor_interval: float = config.POSTGRES_MONITOR_INTERVAL
    listener_connect_timeout: float = 5.0
    listener_retry_delay: float = 1.0
    listener_max_retry_delay: float = 60.0
    cache_hydration_hours: int = config.CACHE_HYDRATION_HOURS


def build_lifespan(
    options: StartupOptions,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        logger.info("Starting WindBurglr application")
        # Callbacks run in reverse on shutdown, or on a failure partway through startup
        async with AsyncExitStack() as stack:
            pool = await stack.enter_async_context(options.open_db_pool())

            cache_backend = create_cache_from_config(config.get_cache_config())
            stack.push_async_callback(cache_backend.cleanup)

            websocket_manager = WebSocketManager()
            stack.push_async_callback(websocket_manager.close_all)

            watchdog_service = WatchdogService(
                scraper_status_timeout_minutes=config.SCRAPER_STATUS_TIMEOUT_MINUTES,
            )
            watchdog_service.set_websocket_manager(websocket_manager)
            stack.callback(watchdog_service.cleanup)

            station_service = StationService(pool)
            wind_service = WindDataService(cache_backend=cache_backend, pool=pool)

            cache_hydrator = CacheHydrator(
                wind_service,
                pool,
                hours=options.cache_hydration_hours,
                default_station=config.DEFAULT_STATION,
            )
            stack.push_async_callback(cache_hydrator.stop)

            async def refresh_cache(reason: str) -> None:
                logger.warning("%s - marking cache as stale", reason)
                await cache_backend.mark_cache_stale()
                cache_hydrator.start()

            async def handle_reconnect() -> None:
                # Notifications sent while disconnected were missed
                await refresh_cache("Postgres listener reconnected")

            async def handle_resumption() -> None:
                await refresh_cache("System resumption detected")

            pg_manager = PostgresNotificationManager(
                cache_backend=cache_backend,
                websocket_manager=websocket_manager,
                connect=options.connect_listener,
                watchdog_service=watchdog_service,
                postgres_monitor_interval=options.postgres_monitor_interval,
                on_reconnect=handle_reconnect,
                initial_retry_delay=options.listener_retry_delay,
                max_retry_delay=options.listener_max_retry_delay,
            )
            stack.push_async_callback(pg_manager.stop)

            suspension_detector = SuspensionDetector()
            suspension_detector.add_resumption_callback(handle_resumption)
            stack.push_async_callback(suspension_detector.stop_monitoring)

            app.state.db_pool = pool
            app.state.cache_backend = cache_backend
            app.state.websocket_manager = websocket_manager
            app.state.watchdog_service = watchdog_service
            app.state.station_service = station_service
            app.state.wind_service = wind_service
            app.state.cache_hydrator = cache_hydrator
            app.state.pg_manager = pg_manager
            app.state.suspension_detector = suspension_detector
            app.state.websocket_ping_timeout = options.websocket_ping_timeout

            await pg_manager.start(connect_timeout=options.listener_connect_timeout)
            await suspension_detector.start_monitoring()
            # In the background: startup and /health/live don't wait for it
            cache_hydrator.start()

            logger.info("Application startup complete")
            try:
                yield
            finally:
                logger.info("Shutting down WindBurglr application")
        logger.info("Application shutdown complete")

    return lifespan
