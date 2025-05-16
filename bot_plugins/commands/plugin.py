"""
plugins/commands/plugin.py - Plugin management command plugin.
Provides subcommands for listing, enabling, and disabling plugins using Discord's extension system.
Usage:
  !plugins list
  !plugins enable <extension>
  !plugins disable <extension>
"""

from discord.ext import commands
from bot_plugins.typing import Ctx
import logging

logger = logging.getLogger(__name__)

USAGE_PLUGINS = "Usage: !plugins <list|enable|disable> [extension]"
USAGE_ENABLE = "Usage: !plugins enable <extension>"
USAGE_DISABLE = "Usage: !plugins disable <extension>"


class PluginManager(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.group(name="plugins", invoke_without_command=True)
    @commands.is_owner()
    async def plugins(self, ctx: Ctx) -> None:
        await ctx.send(USAGE_PLUGINS)
        return

    @plugins.command(name="list")  # type: ignore[arg-type]
    async def list_plugins(self, ctx: Ctx) -> None:
        # List loaded extensions
        loaded = list(self.bot.extensions.keys())
        if not loaded:
            await ctx.send("No extensions loaded.")
            return
        else:
            await ctx.send("Loaded extensions:\n" + "\n".join(loaded))
            return

    @plugins.command(name="enable")  # type: ignore[arg-type]
    async def enable_plugin(self, ctx: Ctx, extension: str) -> None:
        try:
            await self.bot.load_extension(extension)
            await ctx.send(f"Extension '{extension}' has been enabled.")
            return
        except Exception as e:
            await ctx.send(f"Failed to enable extension '{extension}': {e}")
            return

    @plugins.command(name="disable")  # type: ignore[arg-type]
    async def disable_plugin(self, ctx: Ctx, extension: str) -> None:
        try:
            await self.bot.unload_extension(extension)
            await ctx.send(f"Extension '{extension}' has been disabled.")
            return
        except Exception as e:
            await ctx.send(f"Failed to disable extension '{extension}': {e}")
            return


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PluginManager(bot))
