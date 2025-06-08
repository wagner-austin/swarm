"""
plugins/commands/status.py
--------------------------
Reports live bot health/usage statistics.
"""

from typing import Any

from discord.ext import commands

from bot.core import metrics
from ..base import BaseCog

_ENTRY_CMD = "status"

USAGE = f"""
Show bot uptime and message counters.

Usage: !{_ENTRY_CMD}
"""

READABLE = "{:.1f}"


class Status(BaseCog):
    @commands.command(name=_ENTRY_CMD)
    @commands.is_owner()
    async def status(self, ctx: commands.Context[Any]) -> None:
        """
        Show uptime and message counters.
        """
        s = metrics.get_stats()
        uptime = READABLE.format(s["uptime_s"] / 3600)
        await ctx.send(
            "\n".join(
                [
                    f"⏱️ Uptime: {uptime} h",
                    f"📨 Messages processed: {s['discord_messages_processed']}",
                    f"✉️ Messages sent:     {s['messages_sent']}",
                ]
            )
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Status(bot))
