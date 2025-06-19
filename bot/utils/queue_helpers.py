"""Asyncio Queue helper wrappers that automatically update Prometheus gauges.

These tiny helpers centralise the bookkeeping around *asyncio.Queue* objects so
callers no longer have to remember to call ``update_queue_gauge`` after every
queue operation.  Keeping the gauge update co-located with the put/get logic
avoids subtle omissions when new queues are added and removes a lot of
repetitive code.
"""

from __future__ import annotations

import asyncio
from typing import Any, TypeVar

from bot.core.telemetry import update_queue_gauge

T = TypeVar("T")

__all__ = [
    "put_nowait",
    "get",
    "task_done",
]


def put_nowait(q: asyncio.Queue[T], item: T, name: str) -> None:
    """Put *item* into *q* without blocking and refresh its gauge."""
    q.put_nowait(item)
    update_queue_gauge(name, q)


async def get(q: asyncio.Queue[T], name: str) -> T:
    """`await q.get()` and refresh its gauge before returning the item."""
    item: T = await q.get()
    update_queue_gauge(name, q)
    return item


def task_done(q: asyncio.Queue[Any], name: str) -> None:  # noqa: ANN401 – Any fine here
    """Mark one task processed for *q* and refresh its gauge."""
    q.task_done()
    update_queue_gauge(name, q)
