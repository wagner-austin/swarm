from __future__ import annotations

import pytest
from unittest.mock import patch  # Or MagicMock if preferred for the session's method

from bot.core.api.browser.session_manager import SessionManager
from bot.core.settings import settings


@pytest.mark.asyncio
async def test_status_dead(monkeypatch: pytest.MonkeyPatch) -> None:
    # We don't strictly need DeadAfterOne if we're going to mock is_alive directly
    # monkeypatch.setattr(
    #     "bot.core.api.browser.session.create_uc_driver",
    #     lambda *a, **kw: DeadAfterOne(),
    # )
    session_mgr = SessionManager(cfg=settings)
    await session_mgr.start()

    assert session_mgr._session is not None

    # Mock the session's is_alive to return False
    with patch.object(session_mgr._session, "is_alive", return_value=False):
        status_output = session_mgr.status()
        # The status message for a non-alive session is now "Browser not running..."
        # or if _ensure_alive tries to restart and fails, it might be different.
        # Based on current SessionManager.status() logic:
        # If _session exists but is_alive() is false, it reports "Browser not running..."
        assert "not running" in status_output.lower()
        # If we want to specifically test a "DEAD" state if is_alive() was initially true then false,
        # the SessionManager's status logic would need to differentiate that.
        # For now, a non-alive session reports as "not running".
