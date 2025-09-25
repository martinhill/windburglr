import logging
import os
from contextlib import asynccontextmanager

import asyncpg
import sentry_sdk
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sentry_sdk.integrations.asyncpg import AsyncPGIntegration
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

from app.cache import create_cache_from_config
from app.config import (
    LOG_LEVEL,
    POSTGRES_MONITOR_INTERVAL,
    SCRAPER_STATUS_TIMEOUT_MINUTES,
    get_cache_config,
    get_sentry_config,
)
from app.database import create_db_pool
from app.dependencies import (
    get_db_pool,
    set_cache_backend,
    set_db_pool,
    set_pg_manager,
    set_watchdog_service,
    set_websocket_manager,
    set_wind_service,
)
from app.routers import api, health, web, websocket
from app.services.notifications import PostgresNotificationManager
from app.services.watchdog import WatchdogService
from app.services.websocket import WebSocketManager
from app.services.wind_data import WindDataService
from app.utils.suspension_detector import SuspensionDetector

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)-8s - %(name)s - %(message)s",
    datefmt="%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler()],
    force=True,
)

logger = logging.getLogger("windburglr")
logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
logger.info("WindBurglr logger initialized at level: %s", LOG_LEVEL)

# Initialize Sentry
sentry_config = get_sentry_config()
if sentry_config["dsn"]:
    sentry_sdk.init(
        dsn=sentry_config["dsn"],
        integrations=[
            StarletteIntegration(transaction_style="endpoint"),
            FastApiIntegration(transaction_style="endpoint"),
            AsyncPGIntegration(),
        ],
        environment=sentry_config["environment"],
        release=sentry_config["release"],
        traces_sample_rate=1.0,
        profiles_sample_rate=1.0,
    )
    logger = logging.getLogger("windburglr")
    logger.info("Sentry initialized with DSN: %s", sentry_config["dsn"][:50] + "...")


def make_app(
    pg_connection: asyncpg.Connection | None = None,
    config_overrides: dict[str, float] | None = None,
):
    """Create FastAPI application with proper dependency injection."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup - Initialize all dependencies
        logger.info("Starting WindBurglr application")

        # Create cache backend
        cache_config = get_cache_config()
        cache_backend = create_cache_from_config(cache_config)
        set_cache_backend(cache_backend)

        # Create suspension detector
        suspension_detector = SuspensionDetector()

        # Add callback to mark cache as stale on resumption
        async def handle_resumption():
            logger.warning("System resumption detected - marking cache as stale")
            await cache_backend.mark_cache_stale()

        suspension_detector.add_resumption_callback(handle_resumption)
        await suspension_detector.start_monitoring()

        # Create database connection pool
        db_pool = await create_db_pool()
        set_db_pool(db_pool)

        # Create services
        websocket_manager = WebSocketManager()
        set_websocket_manager(websocket_manager)

        # Create watchdog service (will be initialized by PostgresNotificationManager)
        watchdog_service = WatchdogService(
            scraper_status_timeout_minutes=SCRAPER_STATUS_TIMEOUT_MINUTES
        )
        set_watchdog_service(watchdog_service)

        postgres_monitor_interval = (
            config_overrides.get("postgres_monitor_interval", POSTGRES_MONITOR_INTERVAL)
            if config_overrides
            else POSTGRES_MONITOR_INTERVAL
        )
        pg_manager = PostgresNotificationManager(
            cache_backend,
            websocket_manager,
            watchdog_service,
            postgres_monitor_interval,
        )
        set_pg_manager(pg_manager)

        wind_service = WindDataService(cache_backend)
        set_wind_service(wind_service)

        # Optional: inject a custom connection before starting the listener
        if pg_connection:
            pg_manager.set_pg_listener(pg_connection)

        await pg_manager.start_pg_listener()
        logger.info("Application startup complete")

        yield

        # Shutdown
        logger.info("Shutting down WindBurglr application")
        await suspension_detector.stop_monitoring()
        await pg_manager.stop_pg_listener()
        await cache_backend.cleanup()

        # Close database pool
        if db_pool := await get_db_pool(raise_error=False):
            logger.info("Closing database connection pool...")
            await db_pool.close()
            logger.info("Database connection pool closed")

        logger.info("Application shutdown complete")

    app = FastAPI(title="WindBurglr", lifespan=lifespan)

    # Include routers
    app.include_router(web.router)
    app.include_router(api.router)
    app.include_router(websocket.router)
    app.include_router(health.router)

    # Mount static files
    app.mount("/static", StaticFiles(directory="static"), name="static")
    app.mount("/dist", StaticFiles(directory="dist"), name="dist")

    return app


# Create the app instance
app = make_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn_log_level = LOG_LEVEL.lower()

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level=uvicorn_log_level,
        log_config=None,  # Use our logging configuration
    )
