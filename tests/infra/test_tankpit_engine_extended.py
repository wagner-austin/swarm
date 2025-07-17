"""Additional edge-case tests for TankPitEngine using dependency injection."""

from __future__ import annotations

import asyncio
import time
from typing import Any, List

import pytest

from swarm.infra.tankpit.engine import TankPitEngine


class Counter:
    def __init__(self) -> None:  # noqa: D401 – trivial init
        self.calls: list[float] = []

    # bookkeeping helpers record duration; we store it for assertions
    def __call__(self, _direction: str, duration: float) -> None:  # noqa: D401 – callable helper
        self.calls.append(duration)


@pytest.mark.asyncio
async def test_engine_frame_processing_and_bookkeeping() -> None:
    """Engine should echo RX frames and call bookkeeping exactly once."""

    # ------------------------------------------------------------------
    # Queues and helpers
    # ------------------------------------------------------------------
    q_in: asyncio.Queue[tuple[str, bytes]] = asyncio.Queue()
    q_out: asyncio.Queue[bytes] = asyncio.Queue()

    record_counter = Counter()

    task_done_calls: list[str] = []

    def task_done_fn(q: asyncio.Queue[Any], label: str) -> None:  # noqa: ANN001
        task_done_calls.append(label)
        q.task_done()

    # Use default helpers for get/put
    engine = TankPitEngine(
        q_in,
        q_out,
        record_frame_fn=record_counter,
        task_done_fn=task_done_fn,
    )

    await engine.start()

    payload = b"hello"
    await q_in.put(("RX", payload))

    # Allow the event loop to process one frame
    await asyncio.sleep(0)

    # Assertions
    assert await q_out.get() == payload
    assert len(record_counter.calls) == 1
    assert len(task_done_calls) == 1 and task_done_calls[0] == "ws_in"

    await engine.stop()


@pytest.mark.asyncio
async def test_engine_cancellation_cleanup() -> None:
    """Cancelling the engine task should still call bookkeeping for processed frame."""

    q_in: asyncio.Queue[tuple[str, bytes]] = asyncio.Queue()
    q_out: asyncio.Queue[bytes] = asyncio.Queue()

    record_counter = Counter()
    task_done_calls: list[str] = []

    def task_done_fn(q: asyncio.Queue[Any], label: str) -> None:  # noqa: ANN001
        task_done_calls.append(label)
        q.task_done()

    # Slow get helper to allow us to cancel mid-await
    async def slow_get_fn(q: asyncio.Queue[Any], _label: str) -> tuple[str, bytes]:
        return await asyncio.wait_for(q.get(), timeout=1)

    engine = TankPitEngine(
        q_in,
        q_out,
        record_frame_fn=record_counter,
        task_done_fn=task_done_fn,
        get_fn=slow_get_fn,
    )

    await engine.start()

    # Put one frame then cancel quickly
    await q_in.put(("RX", b"bye"))
    await asyncio.sleep(0)
    await engine.stop()

    # Even if cancelled after first frame, bookkeeping should run once
    assert len(record_counter.calls) == 1
    assert len(task_done_calls) == 1
