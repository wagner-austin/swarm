"""TankPitEngine
===============
A minimal asynchronous game-state engine that consumes raw WebSocket frames
from the TankPit mitmproxy addon and can inject responses back.  For now the
engine is only a stub so that the surrounding infrastructure (proxy service
and addon) can create and run it without raising `ImportError`.

The actual game logic will be filled in a later PR.
"""

from __future__ import annotations

import asyncio
import logging
import time

from bot.core.service_base import ServiceABC
from bot.core.telemetry import record_frame
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

    def __init__(self, q_in: asyncio.Queue[_DirFrame], q_out: asyncio.Queue[bytes]) -> None:
        self._in = q_in
        self._out = q_out
        self._task: asyncio.Task[None] | None = None

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

    async def _run(self) -> None:
        """Run the main consume loop (placeholder implementation)."""
        while True:
            direction, payload = await q_get(self._in, "proxy_in")
            try:
                t0 = time.perf_counter()
                # TODO: parse payload and update state. For now we just echo.
                if direction == "RX":
                    # naive echo logic for proof-of-wiring
                    try:
                        q_put(self._out, payload, "proxy_out")
                    except asyncio.QueueFull:
                        from bot.core import alerts

                        alerts.alert("Proxy outbound queue overflow – dropping frame")
            except Exception as exc:  # pragma: no cover – dev aid
                logger.error("TankPitEngine error: %s", exc, exc_info=True)
            finally:
                record_frame(direction, time.perf_counter() - t0)
                q_task_done(self._in, "proxy_in")
