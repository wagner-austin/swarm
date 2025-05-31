import logging
from discord.ext import commands
from bot_core.api.browser_service import BrowserService, default_browser_service
from typing import Any

logger = logging.getLogger(__name__)

USAGE = (
    "Usage:\n"
    "  !browser start [<url>] [visible]\n"
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
        """Control Chrome browser automation."""
        # If no subcommand is given, print usage
        await ctx.send(USAGE)

    @commands.command(name="start", parent=browser)
    async def start(
        self,
        ctx: commands.Context[Any],
        url: str | None = None,
        visible: str | None = None,
    ) -> None:
        """Start a browser session.

        Use '!help browser start' for detailed usage information.
        """
        assert self._browser is not None, "Browser service is not initialized."

        # If visible is True, we want headless to be False (inverse relationship)
        headless = visible is None

        # Log whether we're running in headless mode or not
        logger.info(f"[Browser] Starting browser with headless={headless}")

        msg = await self._browser.start(url=url, headless=headless)
        await ctx.send(msg)

    @commands.command(name="open", parent=browser)
    async def open(self, ctx: commands.Context[Any], url: str | None = None) -> None:
        """Navigate to a URL in the active browser session."""
        assert self._browser is not None, "Browser service is not initialized."
        if not url:
            await ctx.send(USAGE)
            return
        msg = await self._browser.open(url)
        await ctx.send(msg)

    @commands.command(name="screenshot", parent=browser)
    async def screenshot(self, ctx: commands.Context[Any]) -> None:
        """Take a screenshot of the current browser view and send it in the chat."""
        assert self._browser is not None, "Browser service is not initialized."

        # Get screenshot path and message
        filepath, msg = await self._browser.screenshot()

        if not filepath:  # No screenshot was taken
            await ctx.send(msg)
            return

        # Check if the file exists before trying to send it
        import os

        if os.path.exists(filepath):
            # Create a Discord file object from the screenshot path
            from discord import File

            screenshot_file = File(filepath, filename="screenshot.png")

            # Send both the file and the message
            await ctx.send(file=screenshot_file, content=msg)
        else:
            # In case the file doesn't exist (could happen in tests or if there's an error)
            await ctx.send(f"{msg} (File not available to send)")

    @commands.command(name="stop", parent=browser)
    async def stop(self, ctx: commands.Context[Any]) -> None:
        """Stop the current browser session."""
        assert self._browser is not None, "Browser service is not initialized."
        msg = await self._browser.stop()
        await ctx.send(msg)

    @commands.command(name="status", parent=browser)
    async def status(self, ctx: commands.Context[Any]) -> None:
        """Check the current browser session status."""
        assert self._browser is not None, "Browser service is not initialized."
        msg = self._browser.status()
        await ctx.send(msg)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Browser(bot))


__all__ = ["Browser"]
