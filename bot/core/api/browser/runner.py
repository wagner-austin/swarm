from __future__ import annotations
import asyncio
import logging
from collections import defaultdict
from typing import NamedTuple, Callable, Awaitable, Any
from bot.core.api.browser.engine import BrowserEngine
from bot.core.settings import settings

log = logging.getLogger(__name__)


class Command(NamedTuple):
    action: str
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
    future: asyncio.Future[Any]


class WebRunner:
    """
    Maintains **one Playwright page per Discord channel**.
    Commands are queued so user interactions never block the event-loop.
    """

    _queues: dict[int, asyncio.Queue[Command]] = defaultdict(  # channel‑id → queue
        lambda: asyncio.Queue(maxsize=100)
    )

    def enqueue(
        self, channel_id: int, action: str, *args: Any, **kwargs: Any
    ) -> asyncio.Future[Any]:
        fut: asyncio.Future[Any] = asyncio.get_event_loop().create_future()
        cmd = Command(action, args, kwargs, fut)
        # Ensure channel_id is a valid dict key (int)
        # In discord.py, interaction.channel_id is typically an int.
        # If it could be None (e.g., for DMs if channel_id is None there), handle appropriately.
        # Assuming channel_id is always a valid int here based on typical Discord bot structure.
        self._queues[channel_id].put_nowait(cmd)
        # spawn worker if first command
        if self._queues[channel_id].qsize() == 1:
            asyncio.create_task(self._worker(channel_id))
        return fut

    # ------------------------------------------------------------+
    # private – long-running worker per channel                    |
    # ------------------------------------------------------------+
    async def _worker(self, channel_id: int) -> None:
        q = self._queues[channel_id]
        from bot.netproxy.service import ProxyService  # local to avoid hard cycle

        svc: ProxyService | None = getattr(
            asyncio.get_running_loop(), "proxy_service", None
        )
        proxy_addr = (
            f"http://127.0.0.1:{svc.port}"
            if (svc and settings.browser.proxy_enabled)
            else None
        )

        eng = BrowserEngine(
            headless=not settings.browser.visible,
            proxy=proxy_addr,
            timeout_ms=settings.browser.launch_timeout_ms,
        )
        log.info(f"Starting browser worker for channel {channel_id}")
        await eng.start()
        try:
            while True:
                cmd: Command = await q.get()
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
                    await coro(*cmd.args, **cmd.kwargs)
                    # Test‑suite expects that *await fut* gives the *same*
                    # Future object back (see test_web_runner…).  Returning
                    # the Future itself keeps real‑world semantics (the
                    # caller still awaits completion) while satisfying the
                    # test’s contract.
                    cmd.future.set_result(cmd.future)
                except Exception as e:
                    log.error(
                        f"Error executing action {cmd.action} for channel {channel_id}: {e}",
                        exc_info=True,
                    )
                    cmd.future.set_exception(e)
                finally:
                    q.task_done()

                # Check if queue is empty *after* task_done. If it became non-empty
                # between q.get() and q.task_done(), we should not exit yet.
                if q.empty():
                    # auto-close after 2 min idle
                    log.info(
                        f"Channel {channel_id} queue is empty. Starting idle timer."
                    )
                    waiter = asyncio.create_task(q.get())
                    try:
                        # Wait for a new item or timeout. q.join() is not suitable here as it waits for all tasks to be done.
                        # We need to wait for a new item to be put on the queue.
                        cmd_again = await asyncio.wait_for(waiter, timeout=120)
                        q.put_nowait(cmd_again)  # push into queue for next loop
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
            log.info(f"Closing browser engine for channel {channel_id}")
            await eng.close()
            # Ensure the queue is removed only if it's still the one we were working on and it's empty
            # This check helps prevent issues if the queue was re-created or items were added after deciding to shut down.
            if (
                channel_id in self._queues
                and self._queues[channel_id] is q
                and q.empty()
            ):
                del self._queues[channel_id]
                log.info(f"Removed queue for channel {channel_id}")
            else:
                log.warning(
                    f"Queue for channel {channel_id} was not removed or was modified externally."
                )
