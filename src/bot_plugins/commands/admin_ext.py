import logging
from discord.ext import commands
from bot_plugins.typing import Ctx
from typing import Optional

logger = logging.getLogger(__name__)

USAGE_LOAD = "Usage: !load <module>"
USAGE_UNLOAD = "Usage: !unload <module>"
USAGE_RELOAD = "Usage: !reload <module>"


class Extensions(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="load")
    @commands.is_owner()
    async def load_(self, ctx: Ctx, module: Optional[str] = None) -> None:
        """Load a module extension."""
        if module is None:
            await ctx.send(USAGE_LOAD)
            return

        try:
            await ctx.bot.load_extension(module)
            await ctx.send(f"Loaded `{module}`")
        except Exception as e:
            await ctx.send(f"Error loading `{module}`: {str(e)}")
        return

    @commands.command(name="unload")
    @commands.is_owner()
    async def unload_(self, ctx: Ctx, module: Optional[str] = None) -> None:
        """Unload a module extension."""
        if module is None:
            await ctx.send(USAGE_UNLOAD)
            return

        try:
            await ctx.bot.unload_extension(module)
            await ctx.send(f"Unloaded `{module}`")
        except Exception as e:
            await ctx.send(f"Error unloading `{module}`: {str(e)}")
        return

    @commands.command(name="reload")
    @commands.is_owner()
    async def reload_(self, ctx: Ctx, module: Optional[str] = None) -> None:
        """Reload a module extension."""
        if module is None:
            await ctx.send(USAGE_RELOAD)
            return

        try:
            await ctx.bot.unload_extension(module)
            await ctx.bot.load_extension(module)
            await ctx.send(f"Reloaded `{module}`")
        except Exception as e:
            await ctx.send(f"Error reloading `{module}`: {str(e)}")
        return


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Extensions(bot))
