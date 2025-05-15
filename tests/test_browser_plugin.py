import pytest
from discord.ext.commands import Bot
from bot_plugins.commands.browser import Browser
from bot_core.api.browser_service import BrowserService

class DummyUser: id = 123
class DummyCtx: author = DummyUser()


@pytest.mark.asyncio
async def test_browser_command_flow(async_db, monkeypatch, tmp_path):
    # patch download dir
    monkeypatch.setattr("bot_core.settings.settings.browser_download_dir", tmp_path)

    service = BrowserService()
    dummy_bot = Bot(command_prefix="!")
    browser_cog = Browser(bot=dummy_bot, browser_service=service)
    ctx = DummyCtx()

    # start
    await browser_cog.start(ctx, url=None)
    # open (no URL error)
    await browser_cog.open(ctx, url=None)
    # open good
    await browser_cog.open(ctx, url="https://example.com")
    # screenshot
    await browser_cog.screenshot(ctx)
    # status
    await browser_cog.status(ctx)
    # stop
    await browser_cog.stop(ctx)
