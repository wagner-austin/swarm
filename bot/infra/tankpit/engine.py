"""TankPitEngine
===============
A minimal asynchronous game-state engine that consumes raw WebSocket frames
for TankPit and can inject responses back. For now the
engine is only a stub so that the surrounding infrastructure can create and run it without raising `ImportError`.

The actual game logic will be filled in a later PR.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

from bot.core.service_base import ServiceABC
from bot.core.telemetry import record_frame as default_record_frame
from bot.utils.queue_helpers import (
    get as q_get,
    put_nowait as q_put,
    task_done as q_task_done,
)

logger = logging.getLogger(__name__)

_DirFrame = tuple[str, bytes]


class TankPitEngine(ServiceABC):
    """Very small placeholder implementation.

    Parameters
    ----------
    q_in:
        Queue that receives `(direction, payload)` tuples where *direction* is
        either ``"RX"`` (from server) or ``"TX"`` (from client).
    q_out:
        Queue into which the engine can put crafted binary frames that should be
        forwarded upstream to the TankPit server.
    """

    def __init__(
        self,
        q_in: asyncio.Queue[_DirFrame],
        q_out: asyncio.Queue[bytes],
        *,
        in_queue_name: str = "proxy_in",
        out_queue_name: str = "proxy_out",
        record_frame_fn: Callable[[str, float], None] = default_record_frame,
        task_done_fn: Callable[[asyncio.Queue[Any], str], None] = q_task_done,
        get_fn: Callable[[asyncio.Queue[Any], str], Any] = q_get,
        put_nowait_fn: Callable[[asyncio.Queue[Any], Any, str], None] = q_put,
    ) -> None:
        self._in = q_in
        self._out = q_out
        self._in_queue_name = in_queue_name
        self._out_queue_name = out_queue_name
        self._task: asyncio.Task[None] | None = None
        self._record_frame = record_frame_fn
        self._task_done = task_done_fn
        self._get = get_fn
        self._put_nowait = put_nowait_fn

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())
            logger.info("TankPitEngine: background task started")

    async def stop(self, *, graceful: bool = True) -> None:
        """Cancel the background task and clean up."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await asyncio.wait_for(self._task, timeout=1)
            except asyncio.CancelledError:
                pass
        self._task = None

    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def describe(self) -> str:
        return "running" if self.is_running() else "stopped"

    def __del__(self) -> None:  # best-effort safeguard for test shutdown
        if self._task and not self._task.done():
            try:
                self._task.cancel()
            except Exception:
                # Ignore any errors during interpreter shutdown
                pass

    async def _run(self) -> None:
        """Run the main consume loop (placeholder implementation)."""
        while True:
            try:
                # Await the next frame from the proxy queue.
                direction, payload = await self._get(self._in, self._in_queue_name)
            except (asyncio.CancelledError, GeneratorExit):
                # Graceful shutdown requested – exit the loop quietly so that
                # the task finishes without raising unhandled exceptions.
                break

            t0 = time.perf_counter()
            try:
                # TODO: parse payload and update state. For now we just echo.
                if direction == "RX":
                    # naive echo logic for proof-of-wiring
                    try:
                        self._put_nowait(self._out, payload, self._out_queue_name)
                    except asyncio.QueueFull:
                        from bot.core import alerts

                        alerts.alert("Proxy outbound queue overflow – dropping frame")
            except Exception as exc:  # pragma: no cover – dev aid
                logger.error("TankPitEngine error: %s", exc, exc_info=True)
            finally:
                # Always record telemetry and mark task done, even if an error occurred.
                self._record_frame(direction, time.perf_counter() - t0)
                self._task_done(self._in, self._in_queue_name)
