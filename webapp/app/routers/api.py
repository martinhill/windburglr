from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import asyncpg
from fastapi import APIRouter, Depends

from ..config import DEFAULT_STATION, ISO_FORMAT
from ..dependencies import get_db_connection, get_watchdog_service, get_wind_service
from ..models import ScraperHealth, ScraperStatus
from ..services.station import get_station_timezone
from ..services.watchdog import WatchdogService
from ..services.wind_data import WindDataService

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/wind")
async def get_wind_data(
    conn: Annotated[asyncpg.Connection, Depends(get_db_connection)],
    wind_service: Annotated[WindDataService, Depends(get_wind_service)],
    stn: str = DEFAULT_STATION,
    from_time: str | None = None,
    to_time: str | None = None,
    hours: int | None = None,
) -> dict[str, Any]:
    """Get wind data for a station and time range."""
    # Get station timezone for metadata only
    station_tz_name = await get_station_timezone(stn, conn)

    if from_time and to_time:
        # Parse datetime strings as UTC (no timezone conversion)
        start_time = datetime.strptime(from_time, ISO_FORMAT).replace(tzinfo=UTC)
        end_time = datetime.strptime(to_time, ISO_FORMAT).replace(tzinfo=UTC)
    elif hours:
        # For relative time queries, use current UTC time
        now_utc = datetime.now(UTC)
        start_time = now_utc - timedelta(hours=hours)
        end_time = now_utc
    else:
        # Default: last 24 hours in UTC
        now_utc = datetime.now(UTC)
        start_time = now_utc - timedelta(hours=24)
        end_time = now_utc

    # Get data from service
    result = await wind_service.get_cached_or_fresh_data(
        stn, start_time, end_time, conn
    )

    return {
        "station": stn,
        "winddata": result["winddata"],
        "timezone": station_tz_name,
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "cache_hit": result["cache_hit"],
    }


@router.get("/scraper-status")
async def get_scraper_status(
    watchdog_service: Annotated[WatchdogService, Depends(get_watchdog_service)],
) -> list[ScraperStatus]:
    """Get detailed scraper status for all stations from watchdog service."""
    return watchdog_service.get_scraper_status()


@router.get("/scraper-health")
async def get_scraper_health(
    conn: Annotated[asyncpg.Connection, Depends(get_db_connection)],
) -> ScraperHealth:
    """Get overall scraper health status."""
    row = await conn.fetchrow(
        """
        SELECT
            total_stations,
            healthy_stations,
            error_stations,
            stale_stations,
            overall_status
        FROM get_scraper_health()
        """
    )

    return ScraperHealth(**row)
