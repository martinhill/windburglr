import logging
import os
from datetime import timedelta
from functools import cache
from typing import Any

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

DEFAULT_STATION = "CYTZ"
ISO_FORMAT = "%Y-%m-%dT%H:%M:%S"

GTAG_ID = os.environ.get("GOOGLE_TAG_MANAGER_ID", "")

# Cache configuration
DATA_CACHE_HOURS = int(os.environ.get("DATA_CACHE_HOURS", "48"))
CACHE_DURATION = timedelta(hours=DATA_CACHE_HOURS)
ACQUIRE_CONNECTION_TIMEOUT = float(os.environ.get("ACQUIRE_CONNECTION_TIMEOUT", "5.0"))

# Logging configuration
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# Watchdog staleness check configuration
SCRAPER_STATUS_TIMEOUT_MINUTES = int(os.environ.get("SCRAPER_STATUS_TIMEOUT_MINUTES", "5"))

def get_database_url(pooled: bool = False) -> str:
    """Get database URL from environment variables."""
    if pooled:
        return os.environ.get("DATABASE_POOL_URL", os.environ.get("DATABASE_URL", ""))
    return os.environ.get("DATABASE_URL", "")


def get_cache_config() -> dict[str, Any]:
    """Get cache configuration from environment."""
    return {
        "type": os.getenv("CACHE_BACKEND", "memory"),
        "options": {
            "cache_duration_hours": DATA_CACHE_HOURS,
        },
    }


sentry_dotenv_result = load_dotenv(".env.sentry")


@cache
def get_sentry_config() -> dict[str, Any]:
    """Get Sentry configuration from environment."""
    if sentry_dotenv_result:
        logger.info("Loaded Sentry environment variables from dotfile")
    else:
        logger.warning("No Sentry dotfile found, using environment variables")

    environment = os.environ.get("SENTRY_ENVIRONMENT", "development")
    release = os.environ.get("SENTRY_RELEASE", "unknown")

    logger.info(f"Using Sentry environment: {environment}")
    logger.info(f"Using Sentry release: {release}")

    return {
        "dsn": os.environ.get("SENTRY_DSN", ""),
        "environment": environment,
        "release": release,
    }
