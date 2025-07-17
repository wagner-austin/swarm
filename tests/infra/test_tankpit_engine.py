"""Tests for `swarm.infra.tankpit.engine.TankPitEngine`."""

from __future__ import annotations

import asyncio
from typing import Any, Dict

import pytest

from swarm.infra.tankpit.engine import TankPitEngine
from swarm.utils import queue_helpers as qh


@pytest.mark.asyncio
async def test_engine_echo_and_bookkeeping(monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: D401
    """TankPitEngine should echo RX frames and always run bookkeeping.

    The test verifies three things:
    1. A payload placed on the *in* queue with direction "RX" is echoed on the
       *out* queue.
    2. ``record_frame`` is invoked exactly once for the processed frame.
    3. ``queue_helpers.task_done`` is invoked exactly once so that
       ``in_q.unfinished_tasks`` returns ``0`` after the engine is stopped.
    """

    called: dict[str, int] = {"frames": 0, "task_done": 0}

    # Provide a stub record_frame function for dependency injection.
    def fake_record_frame(direction: str, duration_s: float) -> None:
        called["frames"] += 1

    # Wrap the real task_done to keep queue semantics intact while counting.
    original_task_done = qh.task_done

    def counting_task_done(q: asyncio.Queue[Any], name: str) -> None:  # noqa: ANN401
        called["task_done"] += 1
        original_task_done(q, name)

    # Prepare queues and engine.
    in_q: asyncio.Queue[tuple[str, bytes]] = asyncio.Queue(maxsize=1)
    out_q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=1)

    # Custom get/put wrappers for test coverage
    async def test_get(q: asyncio.Queue[Any], name: str) -> Any:
        try:
            result = await qh.get(q, name)
        except (asyncio.CancelledError, GeneratorExit):
            raise
        if q is in_q and name == "ws_in":
            called.setdefault("get", 0)
            called["get"] += 1
        return result

    def test_put(q: asyncio.Queue[Any], item: Any, name: str) -> None:
        if q is out_q and name == "ws_out":
            called.setdefault("put", 0)
            called["put"] += 1
        qh.put_nowait(q, item, name)

    engine = TankPitEngine(
        in_q,
        out_q,
        record_frame_fn=fake_record_frame,
        task_done_fn=counting_task_done,
        get_fn=test_get,
        put_nowait_fn=test_put,
    )
    await engine.start()

    # Send a test frame and give the background task a moment to run.
    await in_q.put(("RX", b"hello"))
    await asyncio.sleep(0.05)  # Small delay for the engine to process.

    # The frame should have been echoed to the out queue.
    assert out_q.qsize() == 1
    echoed_payload = await out_q.get()
    assert echoed_payload == b"hello"

    # Shut the engine down and confirm bookkeeping hooks were run.
    await engine.stop()
    assert called["frames"] == 1
    assert called["task_done"] == 1
    assert called["get"] == 1
    assert called["put"] == 1
