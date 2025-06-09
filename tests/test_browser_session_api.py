import pytest
from pathlib import Path
from bot.core.api.browser_service import BrowserService
from typing import Any


class DummyDriver:
    def __init__(self, *args: Any, **kwargs: Any):
        self.current_url = "about:blank"

    # accept any ctor args silently

    def get(self, url: str) -> None:
        self.current_url = url

    def save_screenshot(self, path: str) -> None:
        Path(path).touch()

    def quit(self) -> None:
        pass

    def close(self) -> None:  # uc.Chrome has close(), not just quit()
        pass


@pytest.mark.asyncio
async def test_start_stop_status(tmp_path: Any, monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "bot.core.api.browser.session.create_uc_driver",
        lambda *a, **kw: DummyDriver(*a, **kw),
    )
    # patch download dir so the test never writes outside tmp
    monkeypatch.setattr("bot.core.settings.settings.browser_download_dir", tmp_path)

    svc = BrowserService()
    # Start
    assert (await svc.start()).startswith("Browser session started")
    assert svc._session is not None
    assert svc.status().startswith("Current state")

    # Screenshot (path exists, returns absolute path)
    # Ensure the session is initialized before trying to access _session directly for screenshot
    # This test primarily tests BrowserService, direct _session access should be minimal
    # or tested in a dedicated BrowserSession test.
    # For now, we assume start() correctly initializes _session.
    assert svc._session is not None, "Session should be initialized by start()"
    dest = await svc.screenshot(str(tmp_path / "shot.png"))  # Use svc.screenshot

    # svc.screenshot now returns a tuple (filepath, message)
    # We need to adjust the assertion based on this. The dummy driver will create the file.
    filepath, msg = dest
    assert filepath is not None, "Filepath should be returned by screenshot"
    assert "Screenshot saved" in msg, "Message should indicate success"
    dest_path = Path(filepath)
    assert dest_path.is_absolute() and dest_path.suffix == ".png"

    # Stop
    assert (await svc.stop()).startswith("Browser session stopped")
    assert svc._session is None
    assert (
        svc.status() == "No active session (default mode: visible)."
    )  # Updated to reflect new default
