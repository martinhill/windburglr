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

from app.cache import create_cache_from_config
from app.config import LOG_LEVEL, get_cache_config, get_sentry_config
from app.database import create_db_pool
from app.dependencies import (
    set_cache_backend,
    set_db_pool,
    set_pg_manager,
    set_websocket_manager,
    set_wind_service,
)
from app.routers import api, health, web, websocket
from app.services.notifications import PostgresNotificationManager
from app.services.websocket import WebSocketManager
from app.services.wind_data import WindDataService

# Initialize Sentry
sentry_config = get_sentry_config()
if sentry_config["dsn"]:
    sentry_sdk.init(
        dsn=sentry_config["dsn"],
        integrations=[
            FastApiIntegration(),
            AsyncPGIntegration(),
        ],
        environment=sentry_config["environment"],
        traces_sample_rate=1.0,
        profiles_sample_rate=1.0,
    )
    logger = logging.getLogger("windburglr")
    logger.info("Sentry initialized with DSN: %s", sentry_config["dsn"][:50] + "...")

# Configure logging
log_level_value = getattr(logging, LOG_LEVEL, logging.INFO)

logging.basicConfig(
    level=log_level_value,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
    force=True,
)

logger = logging.getLogger("windburglr")
logger.info("WindBurglr logger initialized at level: %s", LOG_LEVEL)


def make_app(pg_connection: asyncpg.Connection | None = None):
    """Create FastAPI application with proper dependency injection."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup - Initialize all dependencies
        logger.info("Starting WindBurglr application")

        # Create cache backend
        cache_config = get_cache_config()
        cache_backend = create_cache_from_config(cache_config)
        set_cache_backend(cache_backend)

        # Create database connection pool
        db_pool = await create_db_pool()
        set_db_pool(db_pool)

        # Create services
        websocket_manager = WebSocketManager()
        set_websocket_manager(websocket_manager)

        pg_manager = PostgresNotificationManager(cache_backend, websocket_manager)
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
        await pg_manager.stop_pg_listener()
        await cache_backend.cleanup()
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
