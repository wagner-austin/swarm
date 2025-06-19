"""
plugins/commands/status.py
--------------------------
Live bot health and traffic counters (slash-command `/status`).
"""

import discord
from discord import app_commands
from discord.ext import commands

from bot.core import metrics
from bot.plugins.commands.decorators import background_app_command
from bot.utils.discord_interactions import safe_send

SPACER = " │ "  # visual separator in a single embed field


class Status(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        super().__init__()
        self.bot = bot

    @app_commands.command(
        name="status", description="Shows bot uptime and message counters (owner-only)."
    )
    @app_commands.default_permissions(administrator=True)  # superset of owner
    @background_app_command(defer_ephemeral=True)
    async def status(self, interaction: discord.Interaction) -> None:
        """Reply with wall-clock uptime and traffic counters."""
        s = metrics.get_stats()
        uptime_hms = metrics.format_hms(s["uptime_s"])
        uptime_hrs = f"{s['uptime_s'] / 3600:.1f}"

        # Dynamic counters
        latency_ms = int(self.bot.latency * 1000)  # round ms
        cpu, mem = metrics.get_cpu_mem()
        guilds = len(self.bot.guilds)
        shard_info = (
            f"{self.bot.shard_id + 1}/{self.bot.shard_count}"
            if self.bot.shard_count and self.bot.shard_id is not None
            else "—"
        )

        # Create one tidy embed instead of a plain string wall
        embed = discord.Embed(
            title="Bot status",
            description=f"⏱️ **{uptime_hms}** (≈ {uptime_hrs} h)",
            colour=discord.Colour.green(),
        )
        embed.add_field(
            name="Traffic",
            value=(f"📨 {s['discord_messages_processed']} in{SPACER}✉️ {s['messages_sent']} out"),
            inline=False,
        )

        embed.add_field(
            name="Runtime",
            value=f"🖥️ {cpu} CPU{SPACER}💾 {mem}",
            inline=False,
        )
        embed.add_field(
            name="Discord",
            value=(f"⏰ {latency_ms} ms latency\n🌐 {guilds} guilds\n🔀 Shard {shard_info}"),
            inline=False,
        )

        await safe_send(interaction, embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Status(bot))
