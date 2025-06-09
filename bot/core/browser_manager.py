from __future__ import annotations
import asyncio
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from playwright.async_api import Browser, BrowserContext, Playwright

__all__ = ["BrowserManager", "Runner"]


@dataclass(slots=True)
class Runner:
    channel_id: int
    browser: Browser
    context: BrowserContext
    queue: asyncio.Queue[Any]
    worker_task: asyncio.Task[Any]
    playwright: Optional[Playwright] = None  # new – for graceful shutdown


class BrowserManager:
    """Owns every Playwright engine spun up by the bot."""

    def __init__(self) -> None:
        self._runners: Dict[int, Runner] = {}
        self._lock = asyncio.Lock()

    # public API -------------------------------------------------------------
    async def register(self, runner: Runner) -> None:
        async with self._lock:
            self._runners[runner.channel_id] = runner

    async def unregister(self, channel_id: int) -> None:
        async with self._lock:
            self._runners.pop(channel_id, None)

    async def close_channel(self, channel_id: int) -> None:
        """Close the browser instance for a specific channel."""
        async with self._lock:
            runner = self._runners.pop(channel_id, None)
            if runner is None:
                return

        # Stop the worker task by sending the sentinel
        runner.queue.put_nowait(None)
        try:
            # Wait for worker to complete
            await runner.worker_task
        except asyncio.CancelledError:
            pass

        # Close browser resources
        await runner.context.close()
        await runner.browser.close()
        if runner.playwright:
            await runner.playwright.stop()

    def status_readout(self) -> List[Dict[str, Any]]:
        return [
            {
                "channel": r.channel_id,
                "queue_len": r.queue.qsize(),
                "pages": len(r.context.pages),
                "idle": r.queue.empty() and not r.worker_task.done(),
            }
            for r in self._runners.values()
        ]

    # graceful shutdown -----------------------------------------------------
    async def close_all(self) -> None:
        async with self._lock:
            tasks = list(self._runners.values())
            self._runners.clear()

        for r in tasks:  # sequential—safe on Windows
            r.queue.put_nowait(None)  # sentinel for the worker
            try:
                await r.worker_task  # drain or cancel
            except asyncio.CancelledError:
                pass
            await r.context.close()
            await r.browser.close()
            if r.playwright:
                await r.playwright.stop()


browser_manager = BrowserManager()
