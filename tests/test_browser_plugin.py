import asyncio
import pytest
from bot_plugins.commands import browser as browser_mod
from bot_core.state import BotStateMachine
from bot_core.api.browser_service import BrowserService

# dummy ctx with .author.id so resolve_role() works
class DummyUser: id = 123
class DummyCtx: author = DummyUser()


@pytest.mark.asyncio
async def test_browser_command_flow(async_db, monkeypatch, tmp_path):
    # patch download dir
    monkeypatch.setattr("bot_core.settings.settings.browser_download_dir", tmp_path)

    service = BrowserService()
    plugin = browser_mod.BrowserPlugin(browser_service=service)
    sm = BotStateMachine()

    # start
    msg = await plugin.run_command("start", DummyCtx(), sm)
    assert msg.startswith("Browser session started")

    # open (no URL error)
    err = await plugin.run_command("open", DummyCtx(), sm)
    assert "Usage" in err

    # open good
    ok = await plugin.run_command("open https://example.com", DummyCtx(), sm)
    assert ok.startswith("Navigating")

    # screenshot
    ss = await plugin.run_command("screenshot", DummyCtx(), sm)
    assert ss.startswith("Screenshot saved to")

    # status
    status = await plugin.run_command("status", DummyCtx(), sm)
    assert "Current state" in status

    # stop
    stop = await plugin.run_command("stop", DummyCtx(), sm)
    assert stop.startswith("Browser session stopped")

    # ensure the background navigate() task has finished
    await asyncio.sleep(0)
