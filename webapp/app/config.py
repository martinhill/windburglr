import os
from datetime import timedelta
from typing import Any
from dotenv import load_dotenv


# Get the SENTRY_RELEASE in production, provided via a file in the docker image
load_dotenv(".env.sentry")

DEFAULT_STATION = "CYTZ"
ISO_FORMAT = "%Y-%m-%dT%H:%M:%S"

GTAG_ID = os.environ.get("GOOGLE_TAG_MANAGER_ID", "")

# Cache configuration
DATA_CACHE_HOURS = int(os.environ.get("DATA_CACHE_HOURS", "48"))
CACHE_DURATION = timedelta(hours=DATA_CACHE_HOURS)

# Logging configuration
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()


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

def get_sentry_release() -> str:
    """Get git SHA from environment or fallback to 'unknown'."""
    return os.environ.get("SENTRY_RELEASE", "unknown")


def get_sentry_config() -> dict[str, Any]:
    """Get Sentry configuration from environment."""
    return {
        "dsn": os.environ.get("SENTRY_DSN", ""),
        "environment": os.environ.get("SENTRY_ENVIRONMENT", "development"),
        "release": get_sentry_release(),
    }
