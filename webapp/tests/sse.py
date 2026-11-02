"""A minimal Server-Sent Events client that talks to an ASGI app directly.

httpx's ASGITransport waits for the whole response body, which never ends for a live
stream, so tests drive the app themselves and read the body as it arrives.
"""

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit


@dataclass
class Event:
    event: str
    data: Any
    id: str | None = None


@dataclass
class SSEStream:
    status_code: int
    headers: dict[str, str]
    _messages: asyncio.Queue[dict[str, Any]]
    _buffer: str = ""
    _pending: list[Event] = field(default_factory=list)
    retry: int | None = None
    comments: list[str] = field(default_factory=list)
    ended: bool = False

    async def next_event(self, timeout: float = 1.0) -> Event:
        """The next dispatched event; raises TimeoutError if none arrives in time."""
        async with asyncio.timeout(timeout):
            while not self._pending:
                if self.ended:
                    raise EOFError("stream ended")
                message = await self._messages.get()
                if message["type"] != "http.response.body":
                    continue
                self._buffer += message.get("body", b"").decode()
                self._parse()
                if not message.get("more_body", False):
                    self.ended = True
            return self._pending.pop(0)

    async def next_event_of(self, *names: str, timeout: float = 1.0) -> Event:
        """The next event with one of the given names, skipping others."""
        async with asyncio.timeout(timeout):
            while True:
                event = await self.next_event(timeout=timeout)
                if event.event in names:
                    return event

    async def wait_for_end(self, timeout: float = 1.0) -> None:
        async with asyncio.timeout(timeout):
            while True:
                try:
                    await self.next_event(timeout=timeout)
                except EOFError:
                    return

    def _parse(self) -> None:
        while "\n\n" in self._buffer:
            block, self._buffer = self._buffer.split("\n\n", 1)
            fields: dict[str, str] = {}
            data: list[str] = []
            for line in block.split("\n"):
                name, _, value = line.partition(":")
                value = value.removeprefix(" ")
                if name == "":
                    self.comments.append(value)
                elif name == "data":
                    data.append(value)
                elif name == "retry":
                    self.retry = int(value)
                else:
                    fields[name] = value
            # As in browsers, an event without data isn't dispatched
            if data:
                self._pending.append(
                    Event(
                        event=fields.get("event", "message"),
                        data=json.loads("\n".join(data)),
                        id=fields.get("id"),
                    )
                )


@asynccontextmanager
async def open_sse(
    app: Any, url: str, headers: dict[str, str] | None = None
) -> AsyncIterator[SSEStream]:
    """GET `url` from `app` and stream the response; disconnects on exit."""
    parts = urlsplit(url)
    to_app: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    from_app: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    await to_app.put({"type": "http.request", "body": b"", "more_body": False})
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": parts.path,
        "raw_path": parts.path.encode(),
        "query_string": parts.query.encode(),
        "root_path": "",
        "headers": [(b"host", b"testserver")]
        + [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }
    task = asyncio.create_task(app(scope, to_app.get, from_app.put))
    try:
        async with asyncio.timeout(2):
            start = await from_app.get()
        assert start["type"] == "http.response.start", start
        stream = SSEStream(
            status_code=start["status"],
            headers={k.decode(): v.decode() for k, v in start["headers"]},
            _messages=from_app,
        )
        yield stream
    finally:
        await to_app.put({"type": "http.disconnect"})
        try:
            async with asyncio.timeout(2):
                await task
        except TimeoutError:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            raise AssertionError("the app did not end the stream on disconnect")
