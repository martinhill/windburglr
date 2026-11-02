"""Fan-out of live updates (new observations, scraper status) to open SSE streams."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from ..models import ScraperStatus

logger = logging.getLogger("windburglr.live_updates")


@dataclass(frozen=True)
class LiveEvent:
    """One event on a live-update stream."""

    event: str  # "wind", "backfill", "status" or "heartbeat"
    data: Any  # JSON-serializable payload
    # Set on events carrying observations: the newest observation's timestamp. The
    # browser sends it back as Last-Event-ID when it reconnects.
    id: str | None = None


HEARTBEAT = LiveEvent("heartbeat", {})


def wind_event(point: dict[str, Any]) -> LiveEvent:
    """A single new observation, as produced by `WindDataPoint.model_dump()`."""
    return LiveEvent("wind", point, id=str(point["timestamp"]))


def backfill_event(points: list[Any]) -> LiveEvent:
    """Observations a client missed, as `/api/wind` rows, oldest first."""
    return LiveEvent("backfill", points, id=str(points[-1][0]))


def status_event(status: ScraperStatus) -> LiveEvent:
    return LiveEvent("status", status.model_dump(mode="json"))


class Subscription:
    """One stream's queue of events for a station."""

    def __init__(self, station: str, max_queued: int):
        self.station = station
        self.closed = False
        self._queue: asyncio.Queue[LiveEvent | None] = asyncio.Queue(max_queued)

    def offer(self, event: LiveEvent) -> bool:
        """Queue an event without waiting; False if the queue is full."""
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            return False
        return True

    def close(self) -> None:
        """End the stream once the consumer reaches this point."""
        if not self.closed:
            self.closed = True
            # If the queue is full, the consumer sees `closed` on its next event
            with contextlib.suppress(asyncio.QueueFull):
                self._queue.put_nowait(None)

    async def events(self, heartbeat_interval: float) -> AsyncIterator[LiveEvent]:
        """Yield queued events, and a heartbeat whenever the queue stays empty for
        `heartbeat_interval` seconds; return once the subscription is closed."""
        while not self.closed:
            try:
                event = await asyncio.wait_for(
                    self._queue.get(), timeout=heartbeat_interval
                )
            except TimeoutError:
                yield HEARTBEAT
                continue
            if event is None or self.closed:
                return
            yield event


class LiveUpdateBroadcaster:
    """Hands events for a station to every stream subscribed to it.

    Publishing never waits on a client: a stream that falls `max_queued` events
    behind is closed, and its browser reconnects and catches up from its last event.
    """

    def __init__(self, max_queued: int = 100):
        self.max_queued = max_queued
        self._subscriptions: dict[str, set[Subscription]] = {}
        self._closed = False

    @property
    def connection_count(self) -> int:
        return sum(len(subs) for subs in self._subscriptions.values())

    def subscribe(self, station: str) -> Subscription:
        subscription = Subscription(station, self.max_queued)
        if self._closed:
            # Shutting down: the stream ends straight away
            subscription.close()
            return subscription
        self._subscriptions.setdefault(station, set()).add(subscription)
        logger.info(
            "Live stream opened for station %s, %d open",
            station,
            len(self._subscriptions[station]),
        )
        return subscription

    def unsubscribe(self, subscription: Subscription) -> None:
        subscription.close()
        subs = self._subscriptions.get(subscription.station)
        if subs is None or subscription not in subs:
            return
        subs.discard(subscription)
        if not subs:
            del self._subscriptions[subscription.station]
        logger.info(
            "Live stream closed for station %s, %d open",
            subscription.station,
            len(subs),
        )

    def publish(self, station: str, event: LiveEvent) -> None:
        subs = self._subscriptions.get(station)
        if not subs:
            logger.debug("No live streams for station %s", station)
            return
        logger.debug(
            "Publishing %s event to %d streams for station %s",
            event.event,
            len(subs),
            station,
        )
        for subscription in list(subs):
            if not subscription.offer(event):
                logger.warning(
                    "Live stream for station %s fell behind, closing it", station
                )
                self.unsubscribe(subscription)

    def close_all(self) -> None:
        """End every stream and refuse new ones, e.g. when the server is stopping."""
        self._closed = True
        for subs in list(self._subscriptions.values()):
            for subscription in list(subs):
                self.unsubscribe(subscription)
