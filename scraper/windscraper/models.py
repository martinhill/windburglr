from datetime import datetime
from typing import Any

from pydantic import BaseModel, field_validator


class WindburglrError(Exception):
    pass


class MaxRetriesExceededError(WindburglrError):
    pass


class StaleWindObservationError(WindburglrError):
    pass


class DuplicateObservationError(WindburglrError):
    pass


class WindObs(BaseModel):
    station: str
    direction: int | None
    speed: float
    gust: float | None
    timestamp: datetime

    @field_validator("direction", mode="before")
    @classmethod
    def validate_direction(cls, v: Any) -> int | None:
        if v is None or v == "":
            return None
        if v == "CALM":
            return 0
        if v in ("?", "--"):
            return None
        return int(v)

    @field_validator("speed", mode="before")
    @classmethod
    def validate_speed(cls, v: Any) -> float:
        if v is None or v == "":
            return 0.0
        if v in ("?", "--", "CALM"):
            return 0.0
        return float(v)

    @field_validator("gust", mode="before")
    @classmethod
    def validate_gust(cls, v: Any) -> float | None:
        if v is None or v == "":
            return None
        if v in ("?", "--"):
            return 0.0
        if v == "CALM":
            return 0.0
        return float(v)

    def __str__(self) -> str:
        direction_str = (
            f"{self.direction} deg" if self.direction is not None else "unknown deg"
        )
        speed_str = f"{self.speed}-{self.gust}" if self.gust else f"{self.speed}"
        return f"{self.station} at {self.timestamp}: {direction_str}, {speed_str} kts"
