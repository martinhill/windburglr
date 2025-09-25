import logging
import os
import tomllib
import zoneinfo
from dataclasses import dataclass, field
from datetime import UTC, tzinfo

from dotenv import load_dotenv

# from pydantic import Field, HttpUrl
# from pydantic.dataclasses import dataclass

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def setup_package_logger(level: str = "INFO", log_file: str | None = None):
    logger = logging.getLogger("windscraper")
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(numeric_level)

    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)-6s - %(name)s - %(message)s"
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    handler.setLevel(numeric_level)
    logger.addHandler(handler)

    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


@dataclass
class StationConfig:
    name: str
    url: str
    timeout: int = 15
    headers: dict[str, str] | None = None
    parser: str = "json"
    direction_path: str = "direction"
    speed_path: str = "speed"
    gust_path: str = "gust"
    time_format: str = "%Y-%m-%d %H:%M"
    # Timezone of data source update time - usually UTC
    timezone: tzinfo = UTC
    # Station's local timezone - usually not UTC
    local_timezone: tzinfo = UTC
    # Minimum elapsed time in seconds before data is considered stale
    stale_data_timeout: int = 300  # 5 minutes default

    def __post_init__(self):
        if isinstance(self.timezone, str):
            self.timezone = zoneinfo.ZoneInfo(self.timezone)
        if isinstance(self.local_timezone, str):
            self.local_timezone = zoneinfo.ZoneInfo(self.local_timezone)


@dataclass
class Config:
    stations: list[StationConfig] = field(default_factory=list)
    log_level: str = "INFO"
    refresh_rate: int = 60
    db_url: str | None = None
    output_mode: str = "postgres"  # or "stdout"


def load_config_from_toml(file_path: str) -> Config:
    with open(file_path, "rb") as f:
        data = tomllib.load(f)

    general = data.get("general", {})
    stations_data = data.get("stations", [])

    stations: list[StationConfig] = []
    for station in stations_data:
        headers = station.get("headers", {})
        stations.append(
            StationConfig(
                name=station["name"],
                url=station["url"],
                timeout=station.get("timeout", 15),
                headers=headers if headers else None,
                timezone=station.get("timezone", UTC),
                local_timezone=station["local_timezone"],
                stale_data_timeout=station.get("stale_data_timeout", 300),
            )
        )

    return Config(
        stations=stations,
        log_level=general.get("log_level", "INFO"),
        refresh_rate=general.get("refresh_rate", 60),
        db_url=general.get("db_url"),
        output_mode=general.get("output_mode", "postgres"),
    )


sentry_dotenv_result = load_dotenv(".env.sentry")


def get_sentry_config() -> dict[str, str]:
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
