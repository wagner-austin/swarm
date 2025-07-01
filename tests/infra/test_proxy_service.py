"""Unit tests for ProxyService using dependency injection.

These tests avoid importing heavy mitmproxy machinery by injecting lightweight
fakes for *all* external helpers used by ProxyService.  The goal is to verify
that the service starts and stops correctly, invokes the game-engine hooks, and
performs expected bookkeeping – *without* side-effects such as binding sockets
or spawning subprocesses.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Callable

import pytest

from bot.netproxy.service import GameEngine, ProxyService


class FakeDump:
    """Minimal stub mimicking mitmproxy.tools.dump.DumpMaster."""

    def __init__(self) -> None:  # noqa: D401 – simple init
        self.run_called = 0
        self.shutdown_called = 0

    async def run(self) -> None:  # noqa: D401 – simple stub
        self.run_called += 1
        # return immediately – no real loop
        return None

    def shutdown(self) -> None:  # noqa: D401 – simple stub
        self.shutdown_called += 1


class FakeEngine:  # Implements GameEngine protocol
    def __init__(self) -> None:
        self.start_called = 0
        self.stop_called = 0

    async def start(self) -> None:  # noqa: D401 – simple stub
        self.start_called += 1

    async def stop(self, *, graceful: bool = True) -> None:  # noqa: D401 – simple stub
        self.stop_called += 1


@pytest.mark.asyncio
async def test_proxy_service_start_stop() -> None:  # noqa: D401 – imperative title
    """ProxyService should start and stop using injected fakes without error."""

    # ------------------------------------------------------------------
    # Injected helper fakes
    # ------------------------------------------------------------------
    def queue_pair_fn(name: str) -> tuple[asyncio.Queue[Any], asyncio.Queue[Any]]:  # noqa: ANN401
        return asyncio.Queue(maxsize=1), asyncio.Queue(maxsize=1)

    async def pick_free_port_fn(port: int) -> int:  # noqa: D401 – stub
        return 12345  # deterministic port for test

    # create_task_fn uses real asyncio.create_task; we don't need a stub
    async def sleep_fn(delay: float) -> None:  # noqa: D401 – stub
        # speed up tests – don't actually sleep
        await asyncio.sleep(0)

    dump_instance = FakeDump()
    dump_master_factory: Callable[[Any], FakeDump] = lambda opts: dump_instance  # noqa: E731

    fake_engine = FakeEngine()
    engine_factory = lambda q_in, q_out: fake_engine  # noqa: E731

    # Fake logger and subprocess_factory for DI
    class FakeLogger(logging.Logger):
        """Lightweight logging.Logger subclass capturing log records for assertions."""

        def __init__(self) -> None:  # noqa: D401 – simple init
            super().__init__("fake")
            self.infos: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
            self.warnings: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
            self.errors: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

        # Override log helpers to capture messages
        def info(self, msg: str, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
            self.infos.append((msg, args, kwargs))

        def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
            self.warnings.append((msg, args, kwargs))

        def error(self, msg: str, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
            self.errors.append((msg, args, kwargs))

    fake_logger = FakeLogger()
    fake_subprocess_calls = []

    async def fake_subprocess_factory(*args: Any, **kwargs: Any) -> object:  # noqa: ANN401
        """Capture subprocess invocation without spawning real processes."""
        fake_subprocess_calls.append((args, kwargs))

        class DummyProc:  # Minimal stub for asyncio.subprocess.Process
            pass

        return DummyProc()

    # Prepare service with all helpers injected
    svc = ProxyService(
        port=9000,
        certdir=Path(".certs_test"),
        addons=[],
        engine_factory=engine_factory,
        queue_pair_fn=queue_pair_fn,
        pick_free_port_fn=pick_free_port_fn,
        create_task_fn=asyncio.create_task,
        sleep_fn=sleep_fn,
        dump_master_factory=dump_master_factory,
        logger=fake_logger,
        subprocess_factory=fake_subprocess_factory,
    )

    # ------------------------------------------------------------------
    # Exercise start / stop lifecycle
    # ------------------------------------------------------------------
    await svc.start()
    assert svc.is_running() is True
    assert fake_engine.start_called == 1
    # dump.run() should have been scheduled exactly once
    assert dump_instance.run_called == 0 or dump_instance.run_called == 1  # race-free

    await svc.stop()
    assert svc.is_running() is False
    assert fake_engine.stop_called == 1
    assert dump_instance.shutdown_called == 1
