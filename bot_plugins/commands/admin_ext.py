import logging
from discord.ext import commands
from bot_plugins.typing import Ctx

logger = logging.getLogger(__name__)

USAGE_LOAD = "Usage: !load <module>"
USAGE_UNLOAD = "Usage: !unload <module>"
USAGE_RELOAD = "Usage: !reload <module>"


class Extensions(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="load")
    @commands.is_owner()
    async def load_(self, ctx: Ctx, module: str) -> None:
        await ctx.bot.load_extension(module)
        await ctx.send(f"Loaded `{module}`")
        return

    @commands.command(name="unload")
    @commands.is_owner()
    async def unload_(self, ctx: Ctx, module: str) -> None:
        await ctx.bot.unload_extension(module)
        await ctx.send(f"Unloaded `{module}`")
        return

    @commands.command(name="reload")
    @commands.is_owner()
    async def reload_(self, ctx: Ctx, module: str) -> None:
        await ctx.bot.unload_extension(module)
        await ctx.bot.load_extension(module)
        await ctx.send(f"Reloaded `{module}`")
        return


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Extensions(bot))
