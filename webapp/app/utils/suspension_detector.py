import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("windburglr.suspension")


class SuspensionDetector:
    """Detects system suspension and resumption by monitoring system time."""

    def __init__(self, check_interval: float = 30.0, suspension_threshold: float = 60.0):
        self.check_interval = check_interval
        self.suspension_threshold = suspension_threshold  # seconds
        self.last_check_time = time.time()
        self.monitor_task: asyncio.Task[None] | None = None
        self.resumption_callbacks: list[Callable[[], Any]] = []
        self.is_monitoring = False

    def add_resumption_callback(self, callback: Callable[[], Any]):
        """Add callback to be called when resumption is detected."""
        self.resumption_callbacks.append(callback)

    async def start_monitoring(self):
        """Start monitoring for suspension/resumption."""
        if self.is_monitoring:
            return

        self.is_monitoring = True
        self.last_check_time = time.time()
        self.monitor_task = asyncio.create_task(self._monitor())
        logger.info("Suspension detector started")

    async def stop_monitoring(self):
        """Stop monitoring."""
        self.is_monitoring = False
        if self.monitor_task:
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass
        logger.info("Suspension detector stopped")

    async def _monitor(self):
        """Background monitoring task."""
        while self.is_monitoring:
            try:
                current_time = time.time()
                time_diff = current_time - self.last_check_time

                if time_diff > self.suspension_threshold:
                    logger.warning(
                        "Suspension detected: time jump of %.1f seconds", time_diff
                    )
                    await self._handle_resumption()

                self.last_check_time = current_time
                await asyncio.sleep(self.check_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in suspension monitor: %s", e)
                await asyncio.sleep(5)

    async def _handle_resumption(self):
        """Handle detected resumption by calling all callbacks."""
        logger.info("Handling system resumption - calling %d callbacks",
                   len(self.resumption_callbacks))

        for callback in self.resumption_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback()
                else:
                    callback()
            except Exception as e:
                logger.error("Error in resumption callback: %s", e)
