import pytest
from discord.ext.commands import Bot
from bot_plugins.commands.browser import Browser
from bot_core.api.browser_service import BrowserService

class DummyUser: id = 123
class DummyCtx:
    author = DummyUser()
    def __init__(self):
        self.sent = []
    async def send(self, msg):
        self.sent.append(msg)


@pytest.mark.asyncio
async def test_browser_command_flow(async_db, monkeypatch, tmp_path):
    # patch download dir
    monkeypatch.setattr("bot_core.settings.settings.browser_download_dir", tmp_path)

    service = BrowserService()
    from discord import Intents
    dummy_bot = Bot(command_prefix="!", intents=Intents.default())
    browser_cog = Browser(bot=dummy_bot, browser_service=service)
    ctx = DummyCtx()

    # start
    await browser_cog.start.callback(browser_cog, ctx, url=None)
    # open (no URL error)
    await browser_cog.open.callback(browser_cog, ctx, url=None)
    # open good
    await browser_cog.open.callback(browser_cog, ctx, url="https://example.com")
    # screenshot
    await browser_cog.screenshot.callback(browser_cog, ctx)
    # status
    await browser_cog.status.callback(browser_cog, ctx)
    # stop
    await browser_cog.stop.callback(browser_cog, ctx)
