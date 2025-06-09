# tests/proxy/test_restart_and_port_fallback.py
from __future__ import annotations

from typing import Any

import pytest
from bot.netproxy.service import ProxyService


class MockAddons:
    def add(self, addon_instance: Any) -> None:  # noqa: D401
        """No-op add used by mitmproxy stubs."""
        return None


class DummyDump:
    def __init__(self) -> None:
        self.addons: MockAddons = MockAddons()

    async def run(self) -> None:
        return None

    def shutdown(self) -> None:  # noqa: D401
        return None


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
    msg1: str = await svc.start()  # should fall back to 9001
    await svc.stop()
    msg2: str = await svc.start()  # original 9000 should be free now

    assert "9001" in msg1  # first run picked next port
    assert "9000" in msg2  # second run reclaimed preferred port
