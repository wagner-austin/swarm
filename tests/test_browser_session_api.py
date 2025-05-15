import importlib
import os
from bot_core.api import browser_session_api as bs

def test_start_stop_status(tmp_path, monkeypatch):
    # ensure a clean module-level state
    importlib.reload(bs)

    # patch download dir so the test never writes outside tmp
    monkeypatch.setattr("bot_core.settings.settings.browser_download_dir", tmp_path)

    # Start
    assert bs.start_browser_session().startswith("Browser session started")
    assert bs._session is not None
    assert bs.get_browser_session_status().startswith("Current state")

    # Screenshot (path exists, returns absolute path)
    dest = bs._session.screenshot(tmp_path / "shot.png")
    assert os.path.isabs(dest) and dest.endswith(".png")

    # Stop
    assert bs.stop_browser_session().startswith("Browser session stopped")
    assert bs._session is None
    assert bs.get_browser_session_status() == "No active session."
