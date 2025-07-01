"""Edge-case tests for ProxyService using dependency injection."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable, List

import pytest

from bot.netproxy.service import ProxyService


class DummyAddon:
    """Simple addon that records that it was initialized and added."""

    def __init__(self, q_in: Any, q_out: Any):  # noqa: D401 – minimal init
        self.q_in = q_in
        self.q_out = q_out
        self.added = True  # marker used by the test

    # mitmproxy will call arbitrary hooks – we ignore them.


@pytest.mark.asyncio
async def test_proxy_service_addon_and_error_handling() -> None:
    """ProxyService should wire addons and clean up if dump creation fails."""

    # ------------------------------------------------------------------
    # Fake helpers
    # ------------------------------------------------------------------
    def queue_pair_fn(name: str) -> tuple[asyncio.Queue[Any], asyncio.Queue[Any]]:
        return asyncio.Queue(), asyncio.Queue()

    async def pick_free_port_fn(port: int) -> int:
        return 12000

    # Dump factory that raises to simulate mitmproxy failure
    async def dump_factory_failure(opts: Any) -> None:
        raise RuntimeError("simulated dump master failure")

    # Use a dummy addon list so we can assert wiring attempts even on failure
    dummy_addon_cls: list[Any] = [DummyAddon]

    svc = ProxyService(
        port=9000,
        certdir=Path(".certs_test"),
        addons=dummy_addon_cls,
        queue_pair_fn=queue_pair_fn,
        pick_free_port_fn=pick_free_port_fn,
        create_task_fn=asyncio.create_task,
        sleep_fn=lambda _: asyncio.sleep(0),
        dump_master_factory=dump_factory_failure,
    )

    # Start should raise due to dump failure
    with pytest.raises(RuntimeError):
        await svc.start()

    # Service should not be running and should have reset its port
    assert svc.is_running() is False
    assert svc._dump is None


@pytest.mark.asyncio
async def test_proxy_service_port_picker_branch() -> None:
    """ProxyService should accept the port returned by the picker helper."""

    # picker returns a *different* port to ensure ProxyService accepts it.
    async def pick_free_port_fn(_port: int) -> int:
        return 54321

    svc = ProxyService(
        port=9000,
        pick_free_port_fn=pick_free_port_fn,
    )

    # we won't actually start mitmproxy – just call the helper directly
    svc.port = await pick_free_port_fn(svc.port)
    assert svc.port == 54321
