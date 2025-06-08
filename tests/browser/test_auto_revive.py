from __future__ import annotations

import pytest

from bot.core.api.browser_service import BrowserService
from tests.helpers.dummy_dead_driver import DeadAfterOne


@pytest.mark.asyncio
async def test_auto_revive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "bot.core.api.browser.session.create_uc_driver",
        lambda *args, **kw: DeadAfterOne(),
    )
    svc = BrowserService()
    await svc.start()  # alive
    assert svc.alive()

    # 1️⃣ First navigation succeeds, driver still alive
    await svc.open("https://example.com")
    assert svc.alive()  # still the original driver

    # 2️⃣ Second navigation hits the “invalid session id”,
    #    BrowserService auto-revives, and navigation completes.
    msg = await svc.open("https://example.com")
    assert "navigation complete" in msg.lower()
    assert svc.alive()
