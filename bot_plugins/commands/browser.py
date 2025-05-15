import logging
from discord.ext import commands
from bot_core.api.browser_service import BrowserService, default_browser_service
from bot_core.settings import settings

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
    def __init__(self, bot, browser_service: BrowserService | None = None):
        self.bot = bot
        self.browser = browser_service or default_browser_service

        # ---- test helper -------------------------------------------------
        # If the cog is instantiated manually (as in the unit-tests) the
        # Command objects defined at *class* level never get their ``cog``
        # attribute.  Bind them here so direct calls like
        # ``await Browser.open(ctx, ....)`` work.
        for attr in dir(self.__class__):
            maybe_cmd = getattr(self.__class__, attr, None)
            if isinstance(maybe_cmd, commands.Command) and getattr(maybe_cmd, 'cog', None) is None:
                maybe_cmd.cog = self

    @commands.group(name="browser", invoke_without_command=True)
    @commands.is_owner()
    async def browser(self, ctx):
        # If no subcommand is given, print usage
        await ctx.send(USAGE)

    @browser.command(name="start")
    async def start(self, ctx, url: str = None):
        msg = await self.browser.start(url=url)
        if hasattr(ctx, "send"):
            await ctx.send(msg)
        return msg

    @browser.command(name="open")
    async def open(self, ctx, url: str = None):
        if not url:
            await ctx.send(USAGE)
            return
        msg = await self.browser.open(url)
        if hasattr(ctx, "send"):
            await ctx.send(msg)
        return msg

    @browser.command(name="screenshot")
    async def screenshot(self, ctx):
        msg = await self.browser.screenshot()
        if hasattr(ctx, "send"):
            await ctx.send(msg)
        return msg

    @browser.command(name="stop")
    async def stop(self, ctx):
        msg = await self.browser.stop()
        if hasattr(ctx, "send"):
            await ctx.send(msg)
        return msg

    @browser.command(name="status")
    async def status(self, ctx):
        msg = self.browser.status()
        if hasattr(ctx, "send"):
            await ctx.send(msg)
        return msg

async def setup(bot):
    await bot.add_cog(Browser(bot))
