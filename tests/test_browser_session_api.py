import pytest
from pathlib import Path
from bot.core.api.browser.session_manager import SessionManager
from bot.core.api.browser.actions import BrowserActions
from bot.core.settings import settings
from tests.helpers.drivers import DummyDriver
from typing import Any


@pytest.mark.asyncio
async def test_start_stop_status(tmp_path: Any, monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "bot.core.api.browser.session.create_uc_driver",
        lambda *a, **kw: DummyDriver(*a, **kw),
    )
    # patch download dir so the test never writes outside tmp
    monkeypatch.setattr("bot.core.settings.settings.browser_download_dir", tmp_path)

    session_mgr = SessionManager(cfg=settings)
    browser_actions = BrowserActions(mgr=session_mgr)

    # Start
    assert (await session_mgr.start()).startswith("Browser session started")
    assert session_mgr._session is not None
    # The status message format has changed with SessionManager
    assert "Browser running" in session_mgr.status()

    # Screenshot
    assert session_mgr._session is not None, "Session should be initialized by start()"
    # mock_interaction was previously used for screenshot, but the method signature changed.
    filepath, msg = await browser_actions.screenshot()
    assert "Screenshot saved" in msg
    assert filepath is not None
    path_obj = Path(filepath)
    assert path_obj.exists()
    assert path_obj.is_file()

    # Stop
    assert (await session_mgr.stop()).startswith("Browser session stopped")
    assert session_mgr._session is None
    # The status message for no active session has also changed.
    assert "Browser not running" in session_mgr.status()
