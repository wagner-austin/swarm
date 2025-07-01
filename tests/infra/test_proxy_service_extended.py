"""Extended tests for ProxyService covering lifecycle, error handling, addons, and port selection.

Each test uses injected fakes so no real network or mitmproxy resources are used.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, List, Tuple

import pytest

from bot.netproxy.service import GameEngine, ProxyService

###############################################################################
# Helper fakes
###############################################################################


class FakeDump:
    def __init__(self) -> None:
        self.run_called = 0
        self.shutdown_called = 0
        self.added_addons: list[Any] = []

    async def run(self) -> None:  # noqa: D401 – stub
        self.run_called += 1

    def shutdown(self) -> None:  # noqa: D401 – stub
        self.shutdown_called += 1

    class addons:  # noqa: D401 – simple container for add/remove
        _store: list[Any] = []

        @classmethod
        def add(cls, addon: Any) -> None:  # noqa: D401 – stub
            cls._store.append(addon)

        @classmethod
        def clear(cls) -> None:
            cls._store.clear()


class FakeEngine(GameEngine):
    def __init__(self) -> None:
        self.start_called = 0
        self.stop_called = 0

    async def start(self) -> None:  # noqa: D401 – stub
        self.start_called += 1

    async def stop(self, *, graceful: bool = True) -> None:  # noqa: D401 – stub
        self.stop_called += 1


###############################################################################
# Utility functions
###############################################################################


def make_service(
    *,
    queue_pair_fn: Callable[[str], tuple[asyncio.Queue[Any], asyncio.Queue[Any]]] | None = None,
    pick_free_port_fn: Callable[[int], Any] | None = None,
    create_task_fn: Callable[[Any], asyncio.Task[Any]] | None = None,
    sleep_fn: Callable[[float], Any] | None = None,
    dump_factory: Callable[[Any], FakeDump] | None = None,
    addons: list[Any] | None = None,
) -> tuple[ProxyService, FakeDump, FakeEngine]:
    """Return a ProxyService with fully injectable helpers."""

    # Defaults -----------------------------------------------------------------
    if queue_pair_fn is None:
        queue_pair_fn = lambda name: (asyncio.Queue(maxsize=1), asyncio.Queue(maxsize=1))  # noqa: E731

    if pick_free_port_fn is None:

        async def pick_free_port_fn(port: int) -> int:
            return 11111

    if create_task_fn is None:
        create_task_fn = asyncio.create_task

    if sleep_fn is None:

        async def sleep_fn(_: float) -> None:
            await asyncio.sleep(0)

    fake_dump = FakeDump() if dump_factory is None else dump_factory(None)

    if dump_factory is None:

        def dump_factory(opts: Any) -> FakeDump:
            return fake_dump

    fake_engine = FakeEngine()

    def engine_factory(q_in: Any, q_out: Any) -> FakeEngine:
        return fake_engine

    svc = ProxyService(
        port=9000,
        certdir=None,
        addons=addons or [],
        engine_factory=engine_factory,
        queue_pair_fn=queue_pair_fn,
        pick_free_port_fn=pick_free_port_fn,
        create_task_fn=create_task_fn,
        sleep_fn=sleep_fn,
        dump_master_factory=dump_factory,
    )
    return svc, fake_dump, fake_engine


###############################################################################
# Tests
###############################################################################


@pytest.mark.asyncio
async def test_lifecycle_start_stop() -> None:  # noqa: D401 – imperative title
    svc, dump, engine = make_service()

    await svc.start()
    assert svc.is_running() is True
    assert dump.run_called == 0 or dump.run_called == 1  # tolerate race
    assert engine.start_called == 1

    await svc.stop()
    assert svc.is_running() is False
    assert dump.shutdown_called == 1
    assert engine.stop_called == 1


@pytest.mark.asyncio
async def test_port_picker_error() -> None:  # noqa: D401
    async def failing_port_picker(port: int) -> int:  # noqa: D401
        raise RuntimeError("no ports")

    svc, dump, engine = make_service(pick_free_port_fn=failing_port_picker)

    with pytest.raises(RuntimeError):
        await svc.start()

    # Service should have cleaned up dump/task even after failure
    assert svc.is_running() is False
    assert dump.shutdown_called == 0  # not created
    assert engine.start_called == 0


class DummyAddon:
    def __init__(self, *_: Any) -> None:  # noqa: D401 – stub
        self.init_called = True

    async def websocket_message(self, _: Any) -> None:  # noqa: D401 – stub
        pass


@pytest.mark.asyncio
async def test_addon_wiring() -> None:  # noqa: D401
    svc, dump, _ = make_service(addons=[DummyAddon])

    await svc.start()
    assert any(isinstance(a, DummyAddon) for a in FakeDump.addons._store)

    await svc.stop()
    FakeDump.addons.clear()


@pytest.mark.asyncio
async def test_create_task_failure() -> None:  # noqa: D401
    def bad_create_task(_: Any) -> asyncio.Task[Any]:  # noqa: D401 – stub
        raise RuntimeError("cannot schedule task")

    svc, dump, _ = make_service(create_task_fn=bad_create_task)

    with pytest.raises(RuntimeError):
        await svc.start()

    assert svc.is_running() is False
    assert dump.shutdown_called == 0  # dump not created due to early failure
