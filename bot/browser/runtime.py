"""Centralised browser runtime hub.

This module provides a thread-safe singleton ``runtime`` that owns exactly one
:class:`BrowserEngine` instance per Discord channel.  External code should use
``runtime.enqueue()``, ``runtime.close_channel()``, ``runtime.close_all()``, and
``runtime.status()``.

The implementation closely follows the design notes in *PR #1 – browser runtime
unification*.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from bot.core.settings import Settings
from bot.utils.queue_helpers import (
    get as q_get,
    put_nowait as q_put,
    task_done as q_task_done,
)

from .engine import BrowserEngine
from .types import Command


class _ChannelCtx:
    """Private helper that groups resources for a single Discord channel."""

    def __init__(self) -> None:  # noqa: D401 – simple description is fine
        self.engine: BrowserEngine | None = None
        self.queue: asyncio.Queue[Command] | None = None
        self.task: asyncio.Task[None] | None = None


class BrowserRuntime:
    """Process-wide runtime that multiplexes one BrowserEngine per channel."""

    def __init__(self, settings: Settings) -> None:  # noqa: D401
        # Mapping: Discord channel ID -> _ChannelCtx
        self._ch: dict[int, _ChannelCtx] = defaultdict(_ChannelCtx)
        self._lock = asyncio.Lock()
        self._settings = settings

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------
    async def enqueue(
        self, channel_id: int, action: str, *args: Any, **kwargs: Any
    ) -> asyncio.Future[Any]:
        """Schedule *action* to run for *channel_id* and return a Future.

        The returned :class:`asyncio.Future` resolves with the value returned by
        the corresponding :pyclass:`BrowserEngine` coroutine.
        """
        async with self._lock:
            ctx = self._ch[channel_id]
            if ctx.engine is None:
                ctx.engine = BrowserEngine(
                    headless=self._settings.browser.headless,
                    proxy=None,
                    timeout_ms=60_000,
                )
                await ctx.engine.start()

            if ctx.queue is None:
                ctx.queue = asyncio.Queue(maxsize=self._settings.queues.command)
                ctx.task = asyncio.create_task(self._worker(channel_id))

            fut: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
            cmd: Command = {
                "action": action,
                "args": args,
                "kwargs": kwargs,
                "future": fut,
            }
            q_put(ctx.queue, cmd, f"browser_cmd:{channel_id}")
            return fut

    async def close_channel(self, channel_id: int) -> None:
        """Close and cleanup all resources associated with *channel_id*."""
        async with self._lock:
            ctx = self._ch.pop(channel_id, None)
        if ctx is None:
            return
        if ctx.task and not ctx.task.done():
            ctx.task.cancel()
        if ctx.engine is not None:
            await ctx.engine.close()

    async def close_all(self) -> None:
        """Close every active channel context."""
        async with self._lock:
            # Create a list of channel IDs to avoid issues with modifying the
            # dictionary while iterating over it.
            channel_ids = list(self._ch.keys())
        await asyncio.gather(*(self.close_channel(cid) for cid in channel_ids))

    def status(self) -> list[dict[str, Any]]:
        """Return a lightweight diagnostic snapshot for the /status command."""
        out: list[dict[str, Any]] = []
        for cid, ctx in self._ch.items():
            qlen = ctx.queue.qsize() if ctx.queue else 0
            out.append(
                {
                    "channel": cid,
                    "queue": qlen,
                    "idle": qlen == 0,
                }
            )
        return out

    # ---------------------------------------------------------------------
    # Internal worker
    # ---------------------------------------------------------------------
    async def _worker(self, channel_id: int) -> None:  # noqa: D401
        ctx = self._ch[channel_id]
        # `ctx.engine` and `ctx.queue` are set in `enqueue()` before we reach here
        assert ctx.engine is not None and ctx.queue is not None

        while True:
            cmd: Command = await q_get(ctx.queue, f"browser_cmd:{channel_id}")
            try:
                method = getattr(ctx.engine, cmd["action"])
                result = await method(*cmd["args"], **cmd["kwargs"])
                if not cmd["future"].done():
                    cmd["future"].set_result(result)
            except Exception as exc:  # noqa: BLE001 – bubble up for logging
                if not cmd["future"].done():
                    cmd["future"].set_exception(exc)
            finally:
                q_task_done(ctx.queue, f"browser_cmd:{channel_id}")


# ---------------------------------------------------------------------+
#  Public singleton – retained for backward compatibility               +
# ---------------------------------------------------------------------+

__all__ = ["BrowserRuntime"]
