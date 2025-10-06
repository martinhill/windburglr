import logging
import os
from contextlib import asynccontextmanager

import sentry_sdk
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sentry_sdk.integrations.asyncpg import AsyncPGIntegration
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

from app.config import LOG_LEVEL, get_sentry_config
from app.database import create_db_pool
from app.dependencies import get_cache_backend, get_db_pool, set_db_pool
from app.routers import api, health, web, websocket
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup - Initialize all dependencies
    logger.info("Starting WindBurglr application")

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

    logger.info("Application startup complete")

    yield

    # Shutdown
    logger.info("Shutting down WindBurglr application")
    await suspension_detector.stop_monitoring()
    # await pg_manager.stop_pg_listener()
    cache_backend = await get_cache_backend()
    await cache_backend.cleanup()

    # Close database pool
    if db_pool := await get_db_pool(raise_error=False):
        logger.info("Closing database connection pool...")
        await db_pool.close()
        logger.info("Database connection pool closed")

    logger.info("Application shutdown complete")


# Create the app instance
app = FastAPI(title="WindBurglr", lifespan=lifespan)

# Include routers
app.include_router(web.router)
app.include_router(api.router)
app.include_router(websocket.router)
app.include_router(health.router)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/dist", StaticFiles(directory="dist"), name="dist")


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
