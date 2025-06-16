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
from typing import Any, Dict

from bot.core.settings import COMMAND_QUEUE_MAXSIZE

from .engine import BrowserEngine
from .types import Command


class _ChannelCtx:
    """Private helper that groups resources for a single Discord channel."""

    def __init__(self) -> None:  # noqa: D401 – simple description is fine
        self.engine: BrowserEngine | None = None
        self.queue: "asyncio.Queue[Command]" | None = None
        self.task: asyncio.Task[None] | None = None


class BrowserRuntime:
    """Process-wide runtime that multiplexes one BrowserEngine per channel."""

    def __init__(self) -> None:  # noqa: D401
        # Mapping: Discord channel ID -> _ChannelCtx
        self._ch: Dict[int, _ChannelCtx] = defaultdict(_ChannelCtx)
        self._lock = asyncio.Lock()

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
                    headless=False,
                    proxy=None,
                    timeout_ms=60_000,
                )
                await ctx.engine.start()

            if ctx.queue is None:
                ctx.queue = asyncio.Queue(maxsize=COMMAND_QUEUE_MAXSIZE)
                ctx.task = asyncio.create_task(self._worker(channel_id))

            fut: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
            cmd: Command = {
                "action": action,
                "args": args,
                "kwargs": kwargs,
                "future": fut,
            }
            ctx.queue.put_nowait(cmd)
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
            ch_map = dict(self._ch)
            self._ch.clear()
        await asyncio.gather(*(self.close_channel(cid) for cid in ch_map))

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
            cmd: Command = await ctx.queue.get()
            try:
                method = getattr(ctx.engine, cmd["action"])
                result = await method(*cmd["args"], **cmd["kwargs"])
                if not cmd["future"].done():
                    cmd["future"].set_result(result)
            except Exception as exc:  # noqa: BLE001 – bubble up for logging
                if not cmd["future"].done():
                    cmd["future"].set_exception(exc)
            finally:
                ctx.queue.task_done()


# Public singleton instance for application code
runtime = BrowserRuntime()

__all__ = ["runtime", "BrowserRuntime"]
