from __future__ import annotations

import pytest

from bot.core.api.browser.session_manager import SessionManager
from bot.core.api.browser.actions import BrowserActions
from bot.core.settings import settings
from tests.helpers.drivers import DeadAfterN


@pytest.mark.asyncio
async def test_auto_revive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "bot.core.api.browser.session.create_uc_driver",  # Path to uc_driver creation used by BrowserSession
        lambda *args, **kw: DeadAfterN(n=1),
    )
    session_mgr = SessionManager(cfg=settings)
    browser_actions = BrowserActions(mgr=session_mgr)

    await session_mgr.start()
    assert session_mgr._session is not None and session_mgr._session.is_alive()

    # 1️⃣ First navigation succeeds, driver still alive
    await browser_actions.open("https://example.com")
    assert (
        session_mgr._session is not None and session_mgr._session.is_alive()
    )  # still the original driver

    # 2️⃣ Second navigation hits the “invalid session id”,
    # BrowserActions.open should succeed after SessionManager auto-revives.
    msg = await browser_actions.open("https://example.com/initial")
    assert "navigation complete" in msg.lower()
    assert session_mgr._session is not None and session_mgr._session.is_alive()
