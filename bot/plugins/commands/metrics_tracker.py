"""
Runtime counters for uptime and traffic volume.

This cog uses *public* discord.py gateway hooks – no monkey-patching required.
"""

from __future__ import annotations

import discord  # need both Message & Interaction types
from discord.ext import commands

from bot.core import metrics


class MetricsTracker(commands.Cog):
    """Increment lightweight counters for /status."""

    def __init__(self, bot: commands.Bot) -> None:
        # keep a ref so we can recognise our own messages
        self.bot = bot

    # ------------------------------------------------------------------+
    # Inbound messages – everything the gateway delivers in MESSAGE_CREATE
    # ------------------------------------------------------------------+
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:  # noqa: D401
        """
        *If* the author is **us** → outbound counter.<br>
        Otherwise → inbound counter.
        """
        if (
            self.bot.user  # may be None during early startup
            and message.author.id == self.bot.user.id
        ):
            metrics.increment_message_count()
        else:
            metrics.increment_discord_message_count()

    # ------------------------------------------------------------------+
    # Slash-command / component / autocomplete traffic                  |
    # ------------------------------------------------------------------+
    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction) -> None:  # noqa: D401
        """
        Every **user-initiated Interaction** counts as inbound traffic.

        We ignore pings, heartbeats, and our own follow-ups (those don’t reach `on_interaction` anyway).
        """
        if (
            interaction.type.name != "ping"  # not a gateway keep-alive
            and interaction.user  # guaranteed for app commands
            and (
                self.bot.user is None  # startup race-condition
                or interaction.user.id != self.bot.user.id
            )
        ):
            metrics.increment_discord_message_count()


async def setup(bot: commands.Bot) -> None:  # noqa: D401 – entry point
    await bot.add_cog(MetricsTracker(bot))
