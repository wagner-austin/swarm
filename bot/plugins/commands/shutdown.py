#!/usr/bin/env python
"""
plugins/commands/shutdown.py
----------------------------
Summary: Shutdown command plugin. Shuts down the bot.
Usage:
  @bot shutdown
"""

from discord.ext import commands
from ..base import BaseCog
from bot.plugins.typing import Ctx

_ENTRY_CMD = "shutdown"

USAGE = f"""
Cleanly shut the bot down (owner-only).

Usage: !{_ENTRY_CMD}
"""


class Shutdown(BaseCog):
    @commands.command(name=_ENTRY_CMD)
    @commands.is_owner()
    async def shutdown(self, ctx: Ctx) -> None:
        """Cleanly shut the bot down (owner-only)."""
        await ctx.send("Bot is shutting down…")
        await ctx.bot.close()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Shutdown(bot))
