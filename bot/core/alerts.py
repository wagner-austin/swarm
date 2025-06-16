"""Runtime alert helper
======================

Provides a simple function that any part of the codebase can call to enqueue
an alert message destined for the bot owner.  It hides the plumbing details of
where the global lifecycle singleton lives and whether the alert queue is
ready.
"""

from __future__ import annotations

import asyncio
import logging
import time


logger = logging.getLogger(__name__)


async def send_alert(message: str) -> None:
    """Asynchronously enqueue *message* onto ``lifecycle.alerts_q`` if possible.

    Falls back to logging a warning if the lifecycle is not yet available or
    if the queue is full.
    """

    from bot.core.lifecycle import _lifecycle_singleton  # re-import to get updated ref

    lifecycle = _lifecycle_singleton  # noqa: SLF001 – internal helper
    if lifecycle is None or not hasattr(lifecycle, "alerts_q"):
        logger.warning("Alert not sent – lifecycle not ready: %s", message)
        return

    q: asyncio.Queue[str] = lifecycle.alerts_q

    try:
        q.put_nowait(message)
    except asyncio.QueueFull:
        logger.warning("alerts_q is full; dropping alert: %s", message)
        # Emit a throttled overflow notice so the owner knows messages were lost
        now = time.monotonic()
        last: float = getattr(send_alert, "_last_overflow_notice", 0.0)
        if now - last > 30.0:  # 30-second cooldown
            try:
                q.put_nowait("⚠️ Alert queue overflow – some messages were dropped.")
                setattr(send_alert, "_last_overflow_notice", now)
            except asyncio.QueueFull:
                # If even this fails, we've already logged the overflow above
                pass


def alert(message: str) -> None:  # convenience wrapper, non-awaitable
    """Fire-and-forget alert; schedules the send on the current loop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # Not in an event-loop context yet; log and bail.
        logger.warning("alert() called too early, dropping: %s", message)
        return
    loop.create_task(send_alert(message))


__all__ = ["send_alert", "alert"]
