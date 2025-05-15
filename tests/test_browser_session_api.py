import os
import pytest
import asyncio
from bot_core.api.browser_service import BrowserService

@pytest.mark.asyncio
async def test_start_stop_status(tmp_path, monkeypatch):
    # patch download dir so the test never writes outside tmp
    monkeypatch.setattr("bot_core.settings.settings.browser_download_dir", tmp_path)

    svc = BrowserService()
    # Start
    assert (await svc.start()).startswith("Browser session started")
    assert svc._session is not None
    assert svc.status().startswith("Current state")

    # Screenshot (path exists, returns absolute path)
    dest = svc._session.screenshot(str(tmp_path / "shot.png"))
    assert os.path.isabs(dest) and dest.endswith(".png")

    # Stop
    assert (await svc.stop()).startswith("Browser session stopped")
    assert svc._session is None
    assert svc.status() == "No active session."
