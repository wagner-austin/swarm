import pytest
from discord import Intents
from discord.ext.commands import Bot, Context
from typing import Any, cast

from bot.plugins.commands.browser import Browser
from bot.core.api.browser_service import BrowserService
from tests.helpers.mocks import MockCtx


class DummyUser:
    id = 123


@pytest.mark.asyncio
async def test_browser_command_flow(monkeypatch: Any, tmp_path: Any) -> None:
    # patch download dir
    monkeypatch.setattr("bot.core.settings.settings.browser_download_dir", tmp_path)

    service: BrowserService = BrowserService()

    dummy_bot: Bot = Bot(command_prefix="!", intents=Intents.default())
    browser_cog: Browser = Browser(bot=dummy_bot, browser_service=service)

    # Tell mypy “yes, this is a Context” – runtime code doesn’t care.
    ctx = cast(Context[Any], MockCtx())

    # start
    await browser_cog.start(ctx)
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
