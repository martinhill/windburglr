import tomllib
import zoneinfo
from dataclasses import dataclass, field
from datetime import UTC, tzinfo

# from pydantic import Field, HttpUrl
# from pydantic.dataclasses import dataclass


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
