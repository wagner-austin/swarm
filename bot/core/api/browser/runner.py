from __future__ import annotations
import asyncio
import logging
from collections import defaultdict
from typing import NamedTuple, Callable, Awaitable, Any, Dict
from playwright.async_api import (
    Browser,
    BrowserContext,
    Playwright,
    async_playwright,
)
from bot.core.browser_manager import browser_manager, Runner
from bot.core.api.browser.engine import BrowserEngine
from bot.core.settings import settings

log = logging.getLogger(__name__)


class Command(NamedTuple):
    action: str
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
    future: asyncio.Future[Any]


class WebRunner:
    _active_runners: Dict[int, Runner] = {}
    """
    Maintains **one Playwright page per Discord channel**.
    Commands are queued so user interactions never block the event-loop.
    """

    _queues: dict[int, asyncio.Queue[Command]] = defaultdict(  # channel‑id → queue
        lambda: asyncio.Queue(maxsize=100)
    )

    async def enqueue(
        self, channel_id: int, action: str, *args: Any, **kwargs: Any
    ) -> asyncio.Future[Any]:
        fut: asyncio.Future[Any] = asyncio.get_event_loop().create_future()
        cmd = Command(action, args, kwargs, fut)
        # Ensure channel_id is a valid dict key (int)
        # In discord.py, interaction.channel_id is typically an int.
        # If it could be None (e.g., for DMs if channel_id is None there), handle appropriately.
        # Assuming channel_id is always a valid int here based on typical Discord bot structure.
        command_queue = self._queues[channel_id]
        command_queue.put_nowait(cmd)

        if channel_id not in self._active_runners:
            log.info(f"Creating new browser runner for channel {channel_id}")
            try:
                playwright_obj: Playwright = await async_playwright().start()
                browser_instance = await playwright_obj.chromium.launch(
                    headless=settings.browser.headless,
                    slow_mo=100 if not settings.browser.headless else 0,
                )
                context_instance = await browser_instance.new_context()
                worker_task_instance = asyncio.create_task(
                    self._worker(
                        channel_id, command_queue, context_instance, browser_instance
                    )
                )
                runner_data = Runner(
                    channel_id=channel_id,
                    playwright=playwright_obj,
                    browser=browser_instance,
                    context=context_instance,
                    queue=command_queue,  # This is the command queue the worker will process
                    worker_task=worker_task_instance,
                )
                self._active_runners[channel_id] = runner_data
                await browser_manager.register(runner_data)
                log.info(
                    f"Browser runner for channel {channel_id} registered with BrowserManager."
                )
            except Exception as e:
                log.error(
                    f"Failed to create browser runner for channel {channel_id}: {e}",
                    exc_info=True,
                )
                fut.set_exception(e)
                # Clean up partially created resources if necessary
                if "browser_instance" in locals() and browser_instance:
                    await browser_instance.close()
                if "playwright_obj" in locals():
                    await playwright_obj.stop()
                # No need to unregister from browser_manager if registration failed or didn't happen.
                self._active_runners.pop(channel_id, None)  # Ensure no partial entry
                self._queues.pop(
                    channel_id, None
                )  # Clean up queue if worker failed to start
                return fut

        return fut

    # ------------------------------------------------------------+
    # private – long-running worker per channel                    |
    # ------------------------------------------------------------+
    async def _worker(
        self,
        channel_id: int,
        queue: asyncio.Queue[Command],
        context: BrowserContext,
        browser: Browser,
    ) -> None:
        from bot.netproxy.service import ProxyService  # type-only

        svc: ProxyService | None = getattr(
            asyncio.get_running_loop(), "proxy_service", None
        )
        proxy_addr = (
            f"http://127.0.0.1:{svc.port}"
            if (svc and settings.browser.proxy_enabled)
            else None
        )

        eng = BrowserEngine(
            headless=settings.browser.headless,
            proxy=proxy_addr,
            timeout_ms=settings.browser.launch_timeout_ms,
        )
        # Re‑use the objects we already created – **no eng.start() call**,
        # so nothing extra gets launched.
        eng._playwright = self._active_runners[channel_id].playwright
        eng._browser = browser
        eng._context = context  # <‑‑ keep reference for _ensure_page()
        eng._page = await context.new_page()
        log.info(f"Using pre-created Playwright objects for channel {channel_id}")
        try:
            while True:
                item = await queue.get()
                if item is None:  # Shutdown sentinel
                    queue.task_done()
                    log.info(
                        f"Worker for channel {channel_id} received shutdown sentinel."
                    )
                    break
                cmd: Command = item
                log.debug(f"Channel {channel_id} processing action: {cmd.action}")
                try:
                    # Ensure the action is a valid method in BrowserEngine
                    if not hasattr(eng, cmd.action) or not callable(
                        getattr(eng, cmd.action)
                    ):
                        raise AttributeError(
                            f"BrowserEngine has no callable action '{cmd.action}'"
                        )

                    coro: Callable[..., Awaitable[Any]] = getattr(eng, cmd.action)
                    result = await coro(*cmd.args, **cmd.kwargs)
                    cmd.future.set_result(result)
                except Exception as e:
                    log.error(
                        f"Error executing action {cmd.action} for channel {channel_id}: {e}",
                        exc_info=True,
                    )
                    cmd.future.set_exception(e)
                finally:
                    queue.task_done()

                # Check if queue is empty *after* task_done. If it became non-empty
                # between q.get() and q.task_done(), we should not exit yet.
                if queue.empty():
                    # auto-close after 2 min idle
                    log.info(
                        f"Channel {channel_id} queue is empty. Starting idle timer."
                    )
                    waiter = asyncio.create_task(queue.get())
                    try:
                        # Wait for a new item or timeout. q.join() is not suitable here as it waits for all tasks to be done.
                        # We need to wait for a new item to be put on the queue.
                        cmd_again = await asyncio.wait_for(waiter, timeout=120)
                        queue.put_nowait(cmd_again)  # push into queue for next loop
                        continue
                        log.info(
                            f"Channel {channel_id} received new command, continuing worker."
                        )
                    except asyncio.TimeoutError:
                        waiter.cancel()
                        log.info(
                            f"Channel {channel_id} idle timeout reached. Shutting down worker."
                        )
                        break  # Exit the while loop to close engine and delete queue
        except Exception as e:
            log.error(
                f"Browser worker for channel {channel_id} encountered a critical error: {e}",
                exc_info=True,
            )
        finally:
            log.info(f"Worker for channel {channel_id} stopping.")
            await browser_manager.unregister(channel_id)

            # Close the BrowserEngine instance created by this worker
            if "eng" in locals() and eng is not None:
                log.info(
                    f"Closing browser engine specific to worker for channel {channel_id}"
                )
                await eng.close()

            self._active_runners.pop(channel_id, None)
            log.info(f"Removed active runner entry for channel {channel_id}")

            # Original command queue cleanup logic
            if channel_id in self._queues and self._queues[channel_id] is queue:
                if queue.empty():
                    del self._queues[channel_id]
                    log.info(f"Removed empty command queue for channel {channel_id}")
                else:
                    # If queue is not empty, it means items were added after sentinel or during shutdown.
                    # These items won't be processed. Log this situation.
                    log.warning(
                        f"Command queue for channel {channel_id} was not empty upon worker exit. {queue.qsize()} items remaining."
                    )
                    # Optionally, clear the queue if desired: while not queue.empty(): queue.get_nowait(); queue.task_done()
            elif channel_id in self._queues:
                log.warning(
                    f"Command queue for channel {channel_id} found but was not the instance used by this worker."
                )
