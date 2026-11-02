import logging
import math
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query
from fastapi.sse import EventSourceResponse, ServerSentEvent

from ..config import LIVE_REPLAY_MAX_HOURS, LIVE_RETRY_MS
from ..dependencies import (
    get_live_broadcaster,
    get_live_heartbeat_interval,
    get_watchdog_service,
    get_wind_service,
)
from ..services.live_updates import (
    LiveEvent,
    LiveUpdateBroadcaster,
    backfill_event,
    status_event,
    wind_event,
)
from ..services.watchdog import WatchdogService
from ..services.wind_data import WindDataService

logger = logging.getLogger("windburglr.live")

router = APIRouter(prefix="/api", tags=["live"])


def _sse(event: LiveEvent) -> ServerSentEvent:
    return ServerSentEvent(event=event.event, data=event.data, id=event.id)


def _resume_point(last_event_id: str | None, since: float | None) -> float | None:
    """The timestamp of the newest observation the client already has, if known.

    Last-Event-ID, sent by the browser when it reconnects on its own, is more recent
    than the `since` the stream was first opened with.
    """
    for value in (last_event_id, since):
        if value is None:
            continue
        try:
            timestamp = float(value)
        except ValueError:
            continue
        if math.isfinite(timestamp):
            return timestamp
    return None


async def _missed_observations(
    wind_service: WindDataService, station: str, after: float
) -> list[Any]:
    """Observations newer than `after`, at most LIVE_REPLAY_MAX_HOURS of them."""
    now = time.time()
    start = max(after, now - LIVE_REPLAY_MAX_HOURS * 3600)
    if start >= now:
        return []
    result = await wind_service.get_cached_or_fresh_data(
        station,
        datetime.fromtimestamp(start, UTC),
        datetime.fromtimestamp(now, UTC),
    )
    return [point for point in result["winddata"] if point[0] > after]


@router.get("/live/{station}", response_class=EventSourceResponse)
async def live_updates(
    station: str,
    broadcaster: Annotated[LiveUpdateBroadcaster, Depends(get_live_broadcaster)],
    wind_service: Annotated[WindDataService, Depends(get_wind_service)],
    watchdog_service: Annotated[WatchdogService, Depends(get_watchdog_service)],
    heartbeat_interval: Annotated[float, Depends(get_live_heartbeat_interval)],
    since: Annotated[
        float | None,
        Query(description="Timestamp of the newest observation the client has"),
    ] = None,
    last_event_id: Annotated[str | None, Header()] = None,
) -> AsyncIterator[ServerSentEvent]:
    """Server-Sent Events stream of live updates for a station.

    Events: `status` (scraper status), `backfill` (observations the client missed,
    as `/api/wind` rows), `wind` (one new observation) and `heartbeat` (sent when
    idle, so clients can tell a live stream from a dead one).

    A client that gives `since`, or reconnects with Last-Event-ID, first gets the
    observations it missed; otherwise it gets the latest observation.
    """
    # Subscribe before reading anything, so nothing published meanwhile is lost
    subscription = broadcaster.subscribe(station)
    try:
        yield ServerSentEvent(comment="live updates", retry=LIVE_RETRY_MS)

        if status := watchdog_service.get_station_status_by_name(station):
            yield _sse(status_event(status))

        newest_sent: float | None = None
        resume_from = _resume_point(last_event_id, since)
        if resume_from is not None:
            missed = await _missed_observations(wind_service, station, resume_from)
            if missed:
                newest_sent = missed[-1][0]
                yield _sse(backfill_event(missed))
        if newest_sent is None:
            # Nothing missed, or a fresh client: the latest sets current conditions
            if latest := await wind_service.get_latest_wind_data(station):
                newest_sent = latest["timestamp"]
                yield _sse(wind_event(latest))

        async for event in subscription.events(heartbeat_interval):
            if (
                event.event == "wind"
                and newest_sent is not None
                and event.data["timestamp"] <= newest_sent
            ):
                continue  # Published while we replayed, and already sent
            yield _sse(event)
    finally:
        broadcaster.unsubscribe(subscription)
