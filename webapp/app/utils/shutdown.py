"""React to the server being told to stop, before it waits for open responses.

On SIGINT/SIGTERM uvicorn stops accepting connections, then waits for every open
response to finish before running lifespan shutdown, with no time limit by default.
Live-update streams never finish on their own, so they would hold up a deploy or a
dev-mode reload indefinitely. uvicorn installs its signal handlers with
`signal.signal` before lifespan startup, so the app can chain onto them: end the
streams, then hand the signal on to uvicorn.
"""

import asyncio
import contextlib
import signal
import threading
from collections.abc import Callable, Generator
from types import FrameType
from typing import Any

SHUTDOWN_SIGNALS = (signal.SIGINT, signal.SIGTERM)


@contextlib.contextmanager
def on_shutdown_signal(callback: Callable[[], None]) -> Generator[None]:
    """Run `callback` on the event loop when SIGINT or SIGTERM arrives, then pass the
    signal to the handler that was installed before. Restores that handler on exit.

    Does nothing outside the main thread, where signal handlers can't be set.
    """
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    loop = asyncio.get_running_loop()
    previous: dict[int, Any] = {}

    def handle(sig: int, frame: FrameType | None) -> None:
        loop.call_soon_threadsafe(callback)
        handler = previous[sig]
        if callable(handler):
            handler(sig, frame)
        elif handler == signal.SIG_DFL:
            signal.signal(sig, signal.SIG_DFL)
            signal.raise_signal(sig)

    for sig in SHUTDOWN_SIGNALS:
        previous[sig] = signal.signal(sig, handle)
    try:
        yield
    finally:
        for sig, handler in previous.items():
            # Leave it alone if something has replaced our handler since
            if signal.getsignal(sig) is handle:
                signal.signal(sig, handler)
