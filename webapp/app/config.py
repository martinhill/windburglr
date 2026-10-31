import logging
import os
from datetime import timedelta
from functools import cache
from typing import Any
from urllib.parse import urlsplit

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

DEFAULT_STATION = "CYTZ"
ISO_FORMAT = "%Y-%m-%dT%H:%M:%S"

# Longest window /api/wind will serve, either as ?hours= or as from_time..to_time.
# The UI asks for at most 24 hours (live view) or one local day (day view, up to
# 25 hours across a DST change); a week leaves room for gap-filling after the
# browser has been asleep for a few days.
MAX_QUERY_HOURS = 7 * 24

GTAG_ID = os.environ.get("GOOGLE_TAG_MANAGER_ID", "")

# Cache configuration
DATA_CACHE_HOURS = int(os.environ.get("DATA_CACHE_HOURS", "48"))
CACHE_DURATION = timedelta(hours=DATA_CACHE_HOURS)
ACQUIRE_CONNECTION_TIMEOUT = float(os.environ.get("ACQUIRE_CONNECTION_TIMEOUT", "5.0"))

# Logging configuration
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# Watchdog staleness check configuration
SCRAPER_STATUS_TIMEOUT_MINUTES = int(
    os.environ.get("SCRAPER_STATUS_TIMEOUT_MINUTES", "5")
)

# WebSocket configuration
WEBSOCKET_PING_TIMEOUT = float(os.environ.get("WEBSOCKET_PING_TIMEOUT", "60.0"))

# Postgres listener monitoring configuration
POSTGRES_MONITOR_INTERVAL = float(os.environ.get("POSTGRES_MONITOR_INTERVAL", "30.0"))


def get_database_url(pooled: bool = False) -> str:
    """Get database URL from environment variables."""
    if pooled:
        return os.environ.get("DATABASE_POOL_URL", os.environ.get("DATABASE_URL", ""))
    return os.environ.get("DATABASE_URL", "")


def describe_database_url(database_url: str) -> str:
    """Describe a database URL for logging, without credentials or query parameters."""
    parsed = urlsplit(database_url)
    host = parsed.hostname or "(local socket)"
    port = f":{parsed.port}" if parsed.port else ""
    return f"{host}{port}{parsed.path}"


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

    environment = os.environ.get("SENTRY_ENVIRONMENT", "development")
    release = os.environ.get("SENTRY_RELEASE", "unknown")

    logger.info(f"Using Sentry environment: {environment}")
    logger.info(f"Using Sentry release: {release}")

    return {
        "dsn": os.environ.get("SENTRY_DSN", ""),
        "environment": environment,
        "release": release,
        "traces_sample_rate": _sample_rate("SENTRY_TRACES_SAMPLE_RATE", 0.1),
        "profiles_sample_rate": _sample_rate("SENTRY_PROFILES_SAMPLE_RATE", 0.0),
    }


def _sample_rate(name: str, default: float) -> float:
    """Read a Sentry sample rate (0.0-1.0) from the environment."""
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    try:
        rate = float(value)
    except ValueError:
        logger.warning("Ignoring invalid %s=%r, using %s", name, value, default)
        return default
    return min(max(rate, 0.0), 1.0)
