# tests/proxy/test_restart_and_port_fallback.py
from __future__ import annotations

import pytest

from bot.netproxy.service import ProxyService
from tests._mocks.mocks import DummyDump


@pytest.mark.asyncio
async def test_stop_then_start_uses_same_or_next_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """We should be able to stop ▸ start without crashing."""
    # Patch DumpMaster so we don't spin up real mitmproxy.
    monkeypatch.setattr(
        "bot.netproxy.service.DumpMaster",
        lambda *args, **kwargs: DummyDump(),
    )
    # Patch the OS port check so that the first attempt fails, then succeeds.
    calls: dict[str, int] = {"n": 0}

    def fake_check(_port: int) -> bool:
        calls["n"] += 1
        return calls["n"] > 1  # first call: port busy, afterwards free

    monkeypatch.setattr("bot.utils.net.is_port_free", fake_check)

    svc: ProxyService = ProxyService(port=9000)
    await svc.start()  # should fall back to 9001
    port1 = svc.port
    await svc.stop()
    await svc.start()  # original 9000 should be free now
    port2 = svc.port

    assert port1 == 9001  # first run picked next port
    assert port2 == 9000  # second run reclaimed preferred port
