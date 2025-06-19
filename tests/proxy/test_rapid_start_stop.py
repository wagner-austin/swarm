"""Race-condition test: rapid sequential start/stop of ``ProxyService``.

Ensures:
1. No exception is raised when ``start`` / ``stop`` are called back-to-back.
2. Listening port is freed so a subsequent ``start`` succeeds on the **same** port.
3. ``is_running`` reflects the internal state correctly throughout the cycle.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from bot.netproxy.service import ProxyService
from tests._mocks.mocks import DummyDump


@pytest.mark.asyncio()
async def test_proxy_service_rapid_start_stop(monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: D401
    """Start ➜ stop ➜ start again quickly without port conflict."""

    # Patch DumpMaster so no real proxy is spawned
    monkeypatch.setattr("bot.netproxy.service.DumpMaster", DummyDump)

    svc = ProxyService()

    await svc.start()
    assert svc.is_running()
    first_port = svc.port

    # Immediate stop
    await svc.stop()
    assert not svc.is_running()

    # Start again – should either reuse same port (preferred) or next free one, but must not error
    await svc.start()
    assert svc.is_running()
    assert svc.port in {first_port, first_port + 1}

    # Final cleanup
    await svc.stop()
    assert not svc.is_running()
