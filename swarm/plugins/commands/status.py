"""
plugins/commands/status.py
--------------------------
Live swarm health and traffic counters (slash-command `/status`).
"""

from typing import Any, Callable

import discord
from discord import app_commands
from discord.ext import commands

from swarm.core import metrics as default_metrics
from swarm.frontends.discord.discord_interactions import safe_send as default_safe_send
from swarm.plugins.base_di import BaseDIClientCog
from swarm.plugins.commands.decorators import background_app_command

SPACER = " │ "  # visual separator in a single embed field


class Status(BaseDIClientCog):
    def __init__(
        self,
        *,
        discord_bot: commands.Bot,
        metrics_mod: Any = None,
        safe_send_func: Callable[..., Any] | None = None,
    ) -> None:
        super().__init__(discord_bot)
        self.discord_bot = discord_bot
        self.metrics = metrics_mod if metrics_mod is not None else default_metrics
        self.safe_send = safe_send_func if safe_send_func is not None else default_safe_send

    @app_commands.command(
        name="status", description="Shows swarm uptime and message counters (owner-only)."
    )
    @app_commands.default_permissions(administrator=True)  # superset of owner
    @background_app_command(defer_ephemeral=True)
    async def status(self, interaction: discord.Interaction) -> None:
        """Reply with wall-clock uptime and swarm traffic counters."""
        s = self.metrics.get_stats()
        uptime_hms = self.metrics.format_hms(s["uptime_s"])
        uptime_hrs = f"{s['uptime_s'] / 3600:.1f}"

        # Dynamic counters
        latency_ms = int(self.discord_bot.latency * 1000)  # round ms
        cpu, mem = self.metrics.get_cpu_mem()
        guilds = len(self.discord_bot.guilds)
        shard_info = (
            f"{self.discord_bot.shard_id + 1}/{self.discord_bot.shard_count}"
            if self.discord_bot.shard_count and self.discord_bot.shard_id is not None
            else "—"
        )

        # Create one tidy embed instead of a plain string wall
        embed = discord.Embed(
            title="Swarm Status",
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

        await self.safe_send(interaction, embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Status(discord_bot=bot))


# Note: DI factory should use Status(bot, metrics_mod=..., safe_send_func=...) for injection
