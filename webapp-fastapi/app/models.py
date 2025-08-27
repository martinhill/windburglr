from datetime import datetime, timezone
from typing import Optional, Any
from pydantic import BaseModel, field_validator


class WindDataPoint(BaseModel):
    """Model for wind data observations."""

    timestamp: float
    direction: Optional[int]
    speed_kts: Optional[int]
    gust_kts: Optional[int]

    @field_validator("timestamp", mode="before")
    @classmethod
    def convert_timestamp(cls, ts_value: Any) -> float:
        """Convert datetime objects to Unix timestamps."""
        if isinstance(ts_value, datetime):
            # Ensure both datetimes are timezone-aware
            if ts_value.tzinfo is None:
                ts_value = ts_value.replace(tzinfo=timezone.utc)
            # Convert to UTC if not already
            if ts_value.tzinfo != timezone.utc:
                ts_value = ts_value.astimezone(timezone.utc)
            return ts_value.timestamp()
        return float(ts_value) if ts_value is not None else 0.0
