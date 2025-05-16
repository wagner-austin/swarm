#!/usr/bin/env python
"""
plugins/commands/shutdown.py
----------------------------
Summary: Shutdown command plugin. Shuts down the bot.
Usage:
  @bot shutdown
"""

from discord.ext import commands
from bot_plugins.typing import Ctx


class Shutdown(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="shutdown")
    @commands.is_owner()
    async def shutdown(self, ctx: Ctx) -> None:
        await ctx.send("Bot is shutting down…")
        await ctx.bot.close()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Shutdown(bot))
