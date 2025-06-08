import pytest
from discord import Intents
from discord.ext.commands import Bot
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

    # Treat ctx as Any so we can access the helper attribute “sent”.
    ctx = cast(Any, MockCtx())

    # The attributes `start`, `open`, … are `discord.ext.commands.Command`
    # objects – we need their *coroutine* behind `.callback`.

    # Helper that silences mypy by treating Command.callback as Any
    async def invoke(command_obj: Any, *params: Any, **kw: Any) -> None:
        await cast(Any, command_obj.callback)(*params, **kw)

    # start
    await invoke(browser_cog.start, browser_cog, ctx)

    # open (no URL – should show usage)
    await invoke(browser_cog.open, browser_cog, ctx, url=None)

    # open valid
    await invoke(browser_cog.open, browser_cog, ctx, url="https://example.com")

    # open invalid → our new validation branch
    await invoke(browser_cog.open, browser_cog, ctx, url="qwasd")
    assert any("invalid url" in m.lower() for m in ctx.sent)
    ctx.sent.clear()  # Clear sent messages for the next assertion

    # screenshot
    await invoke(browser_cog.screenshot, browser_cog, ctx)

    # status
    await invoke(browser_cog.status, browser_cog, ctx)

    # close
    await invoke(browser_cog.close, browser_cog, ctx)
