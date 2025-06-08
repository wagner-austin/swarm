"""
plugins/commands/status.py
--------------------------
Live bot health and traffic counters (slash-command `/status`).
"""

import discord
from discord import app_commands
from discord.ext import commands
from bot.core import metrics

READABLE = "{:.1f}"
SPACER = " │ "  # visual separator in a single embed field


class Status(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        super().__init__()
        self.bot = bot

    @app_commands.command(
        name="status", description="Shows bot uptime and message counters (owner-only)."
    )
    @app_commands.default_permissions(administrator=True)  # superset of owner
    async def status(self, interaction: discord.Interaction) -> None:
        """Reply with wall-clock uptime and traffic counters."""
        s = metrics.get_stats()
        uptime_hms = metrics.format_hms(s["uptime_s"])
        uptime_hrs = READABLE.format(s["uptime_s"] / 3600)

        # Create one tidy embed instead of a plain string wall
        embed = discord.Embed(
            title="Bot status",
            description=f"⏱️ **{uptime_hms}** (≈ {uptime_hrs} h)",
            colour=discord.Colour.green(),
        )
        embed.add_field(
            name="Traffic",
            value=(
                f"📨 {s['discord_messages_processed']} in"
                f"{SPACER}"
                f"✉️ {s['messages_sent']} out"
            ),
            inline=False,
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Status(bot))
