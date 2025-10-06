import os
import zoneinfo
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..config import DEFAULT_STATION, GTAG_ID, get_sentry_config
from ..dependencies import get_dist_css_files, get_dist_js_files, get_station_service
from ..services.station import StationService

router = APIRouter(tags=["web"])
templates = Jinja2Templates(directory="templates")


@router.get("/", response_class=HTMLResponse)
async def live_wind_chart(
    request: Request, stn: str = DEFAULT_STATION, hours: int = 3, minutes: int = 0
):
    """Main page with live wind chart."""
    sentry_config = get_sentry_config()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "gtag_id": GTAG_ID,
            "station": stn,
            "hours": hours,
            "minutes": minutes,
            "is_live": True,
            "dev_mode": os.getenv("DEV_MODE", "false").lower() == "true",
            "dist_js_files": get_dist_js_files(),
            "dist_css_files": get_dist_css_files(),
            "sentry_dsn": sentry_config["dsn"],
            "sentry_environment": sentry_config["environment"],
            "sentry_release": sentry_config["release"],
        },
    )


@router.get("/day")
async def redirect_to_today(stn: str = DEFAULT_STATION, hours: int = 24):
    """Redirect to current date when no date is specified."""
    today = datetime.now().strftime("%Y-%m-%d")
    return RedirectResponse(
        url=f"/day/{today}?stn={stn}&hours={hours}", status_code=302
    )


@router.get("/day/{date}", response_class=HTMLResponse)
async def historical_wind_day_chart(
    request: Request,
    date: str,
    station_service: Annotated[StationService, Depends(get_station_service)],
    stn: str = DEFAULT_STATION,
    hours: int = 24,
):
    """Historical wind chart for a specific date."""
    try:
        # Parse ISO date (YYYY-MM-DD) - simple validation
        selected_date = datetime.strptime(date, "%Y-%m-%d")

        # Calculate previous and next dates
        prev_date = selected_date - timedelta(days=1)
        next_date = selected_date + timedelta(days=1)

        # Get station timezone to convert local day boundaries to UTC
        station_tz_name = await station_service.get_station_timezone(stn)
        station_tz = zoneinfo.ZoneInfo(station_tz_name)

        # Create day boundaries in station timezone, then convert to UTC
        day_start_local = selected_date.replace(
            hour=0, minute=0, second=0, microsecond=0, tzinfo=station_tz
        )
        day_end_local = day_start_local + timedelta(days=1)

        day_start_utc = day_start_local.astimezone(UTC)
        day_end_utc = day_end_local.astimezone(UTC)

        sentry_config = get_sentry_config()
        return templates.TemplateResponse(
            request=request,
            name="day.html",
            context={
                "gtag_id": GTAG_ID,
                "station": stn,
                "hours": hours,
                "minutes": 0,
                "is_live": False,
                "selected_date": selected_date.strftime("%Y-%m-%d"),
                "selected_date_obj": selected_date,
                "prev_date": prev_date.strftime("%Y-%m-%d"),
                "next_date": next_date.strftime("%Y-%m-%d"),
                "date_start": day_start_utc.strftime("%Y-%m-%dT%H:%M:%S"),
                "date_end": day_end_utc.strftime("%Y-%m-%dT%H:%M:%S"),
                "station_timezone": station_tz_name,
                "dev_mode": os.getenv("DEV_MODE", "false").lower() == "true",
                "dist_js_files": get_dist_js_files(),
                "dist_css_files": get_dist_css_files(),
                "sentry_dsn": sentry_config["dsn"],
                "sentry_environment": sentry_config["environment"],
                "sentry_release": sentry_config["release"],
            },
        )
    except ValueError as err:
        raise HTTPException(
            status_code=400, detail="Invalid date format. Use YYYY-MM-DD"
        ) from err
