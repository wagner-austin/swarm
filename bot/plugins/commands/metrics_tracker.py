"""
plugins/metrics_tracker.py
--------------------------
Hidden cog that feeds the counters in ``bot.core.metrics``.
"""

from typing import Any

from discord.ext import commands
from bot.core import metrics


class MetricsTracker(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        super().__init__()
        # Patch Context.send once at start-up
        metrics.patch_discord_context_send()

    # ------------------------------------------------------------------+
    # Listeners                                                         |
    # ------------------------------------------------------------------+

    @commands.Cog.listener()
    async def on_message(self, _message: Any) -> None:
        """Count *every* message (including non-commands)."""
        metrics.increment_discord_message_count()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MetricsTracker(bot))
