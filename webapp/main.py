import logging
import os

import sentry_sdk
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sentry_sdk.integrations.asyncpg import AsyncPGIntegration
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

from app.config import LOG_LEVEL, get_sentry_config
from app.lifespan import StartupOptions, build_lifespan
from app.routers import api, health, web, websocket

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
        traces_sample_rate=sentry_config["traces_sample_rate"],
        profiles_sample_rate=sentry_config["profiles_sample_rate"],
    )
    logger = logging.getLogger("windburglr")
    logger.info("Sentry initialized with DSN: %s", sentry_config["dsn"][:50] + "...")


def create_app(options: StartupOptions | None = None) -> FastAPI:
    """Build the app; its services are created by the lifespan when it starts."""
    app = FastAPI(
        title="WindBurglr", lifespan=build_lifespan(options or StartupOptions())
    )

    app.include_router(web.router)
    app.include_router(api.router)
    app.include_router(websocket.router)
    app.include_router(health.router)

    app.mount("/static", StaticFiles(directory="static"), name="static")
    app.mount("/dist", StaticFiles(directory="dist"), name="dist")
    return app


app = create_app()


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
