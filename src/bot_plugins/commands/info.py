#!/usr/bin/env python
"""
plugins/commands/info.py
------------------------
Summary: Info command plugin. Displays bot information.
Usage:
  @bot info
"""

from discord.ext import commands
from src.bot_plugins.typing import Ctx
import logging

logger = logging.getLogger(__name__)

USAGE = "Usage: @bot info"


class Info(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        for cmd in self.get_commands():
            cmd.cog = self

    @commands.command(name="info")
    async def info(self, ctx: Ctx) -> None:
        try:
            await ctx.send("Hi! I’m the personal Discord bot.")
            return
        except Exception:
            await ctx.send("An internal error occurred. Please try again later.")
            return


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Info(bot))
