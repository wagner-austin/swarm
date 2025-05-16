import pytest
from bot_core.api.browser_service import BrowserService

from typing import Any


@pytest.mark.asyncio
async def test_start_stop_status(tmp_path: Any, monkeypatch: Any) -> None:
    # patch download dir so the test never writes outside tmp
    monkeypatch.setattr("bot_core.settings.settings.browser_download_dir", tmp_path)

    svc = BrowserService()
    # Start
    assert (await svc.start()).startswith("Browser session started")
    assert svc._session is not None
    assert svc.status().startswith("Current state")

    # Screenshot (path exists, returns absolute path)
    dest = svc._session.screenshot(str(tmp_path / "shot.png"))
    from pathlib import Path

    dest_path = Path(dest)
    assert dest_path.is_absolute() and dest_path.suffix == ".png"

    # Stop
    assert (await svc.stop()).startswith("Browser session stopped")
    assert svc._session is None
    assert svc.status() == "No active session."
