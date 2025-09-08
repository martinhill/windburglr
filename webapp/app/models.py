from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, field_validator


class WindDataPoint(BaseModel):
    """Model for wind data observations."""

    timestamp: float
    direction: int | None
    speed_kts: int | None
    gust_kts: int | None

    @field_validator("timestamp", mode="before")
    @classmethod
    def convert_timestamp(cls, ts_value: Any) -> float:
        """Convert datetime objects to Unix timestamps."""
        if isinstance(ts_value, datetime):
            # Ensure both datetimes are timezone-aware
            if ts_value.tzinfo is None:
                ts_value = ts_value.replace(tzinfo=UTC)
            # Convert to UTC if not already
            if ts_value.tzinfo != UTC:
                ts_value = ts_value.astimezone(UTC)
            return ts_value.timestamp()
        return float(ts_value) if ts_value is not None else 0.0
