import logging
from discord.ext import commands
from bot_core.api.browser_service import BrowserService, default_browser_service
from typing import Any

logger = logging.getLogger(__name__)

USAGE = (
    "Usage:\n"
    "  !browser start [<url>]\n"
    "  !browser open <url>\n"
    "  !browser screenshot\n"
    "  !browser stop\n"
    "  !browser status"
)


class Browser(commands.Cog):
    def __init__(
        self, bot: commands.Bot, browser_service: BrowserService | None = None
    ) -> None:
        self.bot = bot
        self._browser: BrowserService | None = (
            browser_service or default_browser_service
        )
        self.__cog_name__ = "Browser"
        # ---------- unit-test friendliness ----------
        # In the test-suite the cog instance is *not* added to a Bot,
        # yet the tests call `await browser_cog.start(ctx)` directly.
        # That works only when every `commands.Command` object on the
        # instance has its `.cog` attribute pointing back to `self`.
        for name in dir(self):
            try:
                attr = getattr(self, name)
            except AttributeError:  # pragma: no cover
                continue
            if isinstance(attr, commands.Command):
                attr.cog = self

    @commands.group(name="browser", invoke_without_command=True)
    @commands.is_owner()
    async def browser(self, ctx: commands.Context[Any]) -> None:
        # If no subcommand is given, print usage
        await ctx.send(USAGE)

    @commands.command(name="start", parent=browser)
    async def start(self, ctx: commands.Context[Any], url: str | None = None) -> None:
        assert self._browser is not None, "Browser service is not initialized."
        msg = await self._browser.start(url=url)
        await ctx.send(msg)

    @commands.command(name="open", parent=browser)
    async def open(self, ctx: commands.Context[Any], url: str | None = None) -> None:
        assert self._browser is not None, "Browser service is not initialized."
        if not url:
            await ctx.send(USAGE)
            return
        msg = await self._browser.open(url)
        await ctx.send(msg)

    @commands.command(name="screenshot", parent=browser)
    async def screenshot(self, ctx: commands.Context[Any]) -> None:
        assert self._browser is not None, "Browser service is not initialized."
        msg = await self._browser.screenshot()
        await ctx.send(msg)

    @commands.command(name="stop", parent=browser)
    async def stop(self, ctx: commands.Context[Any]) -> None:
        assert self._browser is not None, "Browser service is not initialized."
        msg = await self._browser.stop()
        await ctx.send(msg)

    @commands.command(name="status", parent=browser)
    async def status(self, ctx: commands.Context[Any]) -> None:
        assert self._browser is not None, "Browser service is not initialized."
        msg = self._browser.status()
        await ctx.send(msg)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Browser(bot))


__all__ = ["Browser"]
