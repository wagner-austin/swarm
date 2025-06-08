"""
plugins/commands/status.py
--------------------------
Reports live bot health/usage statistics.
"""

import discord
from discord import app_commands
from discord.ext import commands
from bot.core import metrics

READABLE = "{:.1f}"


class Status(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        super().__init__()
        self.bot = bot

    @app_commands.command(
        name="status", description="Shows bot uptime and message counters (owner-only)."
    )
    @app_commands.default_permissions(administrator=True)  # superset of owner
    async def status(self, interaction: discord.Interaction) -> None:
        """
        Show uptime and message counters.
        """
        s = metrics.get_stats()
        uptime = READABLE.format(s["uptime_s"] / 3600)
        await interaction.response.send_message(
            "\n".join(
                [
                    f"⏱️ Uptime: {uptime} h",
                    f"📨 Messages processed: {s['discord_messages_processed']}",
                    f"✉️ Messages sent:     {s['messages_sent']}",
                ]
            ),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Status(bot))
