from dataclasses import dataclass
from datetime import datetime


# Internal exceptions that must be handled by the scraper
class WindburglrError(Exception):
    pass


class MaxRetriesExceededError(WindburglrError):
    pass


class StaleWindObservationError(WindburglrError):
    pass


class DuplicateObservationError(WindburglrError):
    pass


@dataclass
class WindObs:
    station: str
    direction: int | None
    speed: float
    gust: float | None
    timestamp: datetime

    def __str__(self):
        direction_str = (
            f"{self.direction} deg" if self.direction is not None else "unknown deg"
        )
        speed_str = f"{self.speed}-{self.gust}" if self.gust else f"{self.speed}"
        return f"{self.station} at {self.timestamp}: {direction_str}, {speed_str} kts"
