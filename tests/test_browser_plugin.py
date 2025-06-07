import pytest
from discord.ext.commands import Bot
from discord import Intents
from src.bot_plugins.commands.browser import Browser
from src.bot_core.api.browser_service import BrowserService
from tests.helpers.mocks import MockCtx
from typing import Any


class DummyUser:
    id = 123


@pytest.mark.asyncio
async def test_browser_command_flow(
    async_db: Any, monkeypatch: Any, tmp_path: Any
) -> None:
    # patch download dir
    monkeypatch.setattr("bot_core.settings.settings.browser_download_dir", tmp_path)

    service: BrowserService = BrowserService()

    dummy_bot: Bot = Bot(command_prefix="!", intents=Intents.default())
    browser_cog: Browser = Browser(bot=dummy_bot, browser_service=service)
    ctx: MockCtx = MockCtx()

    # start
    await browser_cog.start(ctx)  # type: ignore[arg-type]
    # open (no URL error)
    await browser_cog.open(ctx, url=None)  # type: ignore[arg-type]
    # open good
    await browser_cog.open(ctx, url="https://example.com")  # type: ignore[arg-type]
    # screenshot
    await browser_cog.screenshot(ctx)  # type: ignore[arg-type]
    # status
    await browser_cog.status(ctx)  # type: ignore[arg-type]
    # stop
    await browser_cog.stop(ctx)  # type: ignore[arg-type]
