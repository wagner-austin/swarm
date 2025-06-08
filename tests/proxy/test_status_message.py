from __future__ import annotations

from typing import Any

import pytest
from bot.infra.tankpit.proxy.service import ProxyService

# ── tiny in-house mitmproxy stub (same pattern as in test_restart_and_port_fallback) ──

class _DummyAddons:
    def add(self, _addon: Any) -> None:
        return None


class _DummyDump:
    def __init__(self) -> None:
        self.addons: _DummyAddons = _DummyAddons()

    async def run(self) -> None:  # noqa: D401
        return None

    def shutdown(self) -> None:  # noqa: D401
        return None


@pytest.mark.asyncio
async def test_status_string(monkeypatch: pytest.MonkeyPatch) -> None:
    # Stub DumpMaster & WSAddon so no real mitmproxy spins up
    monkeypatch.setattr(
        "bot.infra.tankpit.proxy.service.DumpMaster",
        lambda *a, **k: _DummyDump(),
    )
    monkeypatch.setattr(
        "bot.infra.tankpit.proxy.service.WSAddon", lambda *a, **k: object()
    )
    svc = ProxyService(port=9000)
    # stopped ⇒ plain “stopped”
    assert svc.describe() == "stopped"

    await svc.start()
    text = svc.describe()
    assert text.startswith("running on http://127.0.0.1:9000")
    assert "0 inbound" in text and "0 outbound" in text
    await svc.stop()
