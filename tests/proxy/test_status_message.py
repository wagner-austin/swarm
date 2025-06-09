from __future__ import annotations


import pytest
from bot.netproxy.service import ProxyService
from tests.helpers.mocks import DummyDump as _DummyDump

# ── tiny in-house mitmproxy stub (same pattern as in test_restart_and_port_fallback) ──


@pytest.mark.asyncio
async def test_status_string(monkeypatch: pytest.MonkeyPatch) -> None:
    # Stub DumpMaster & WSAddon so no real mitmproxy spins up
    monkeypatch.setattr(
        "bot.netproxy.service.DumpMaster",
        lambda *a, **k: _DummyDump(),
    )
    svc = ProxyService(port=9000)
    # stopped ⇒ plain “stopped”
    assert svc.describe() == "stopped"

    await svc.start()
    text = svc.describe()
    assert text.startswith("running on http://127.0.0.1:9000")
    assert "0 inbound" in text and "0 outbound" in text
    await svc.stop()
