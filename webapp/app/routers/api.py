from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional

from fastapi import APIRouter, Depends

from ..config import DEFAULT_STATION, ISO_FORMAT
from ..dependencies import get_db_pool, get_wind_service
from ..services.station import get_station_timezone

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/wind")
async def get_wind_data(
    pool=Depends(get_db_pool),
    wind_service=Depends(get_wind_service),
    stn: str = DEFAULT_STATION,
    from_time: Optional[str] = None,
    to_time: Optional[str] = None,
    hours: Optional[int] = None,
) -> Dict[str, Any]:
    """Get wind data for a station and time range."""
    # Get station timezone for metadata only
    station_tz_name = await get_station_timezone(stn, pool)

    if from_time and to_time:
        # Parse datetime strings as UTC (no timezone conversion)
        start_time = datetime.strptime(from_time, ISO_FORMAT).replace(
            tzinfo=timezone.utc
        )
        end_time = datetime.strptime(to_time, ISO_FORMAT).replace(tzinfo=timezone.utc)
    elif hours:
        # For relative time queries, use current UTC time
        now_utc = datetime.now(timezone.utc)
        start_time = now_utc - timedelta(hours=hours)
        end_time = now_utc
    else:
        # Default: last 24 hours in UTC
        now_utc = datetime.now(timezone.utc)
        start_time = now_utc - timedelta(hours=24)
        end_time = now_utc

    # Get data from service
    result = await wind_service.get_cached_or_fresh_data(
        stn, start_time, end_time, pool
    )

    return {
        "station": stn,
        "winddata": result["winddata"],
        "timezone": station_tz_name,
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "cache_hit": result["cache_hit"],
    }
