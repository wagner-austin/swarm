"""
plugins/commands/status.py
--------------------------
Live swarm health and traffic counters (slash-command `/status`).
"""

from __future__ import annotations

from typing import Protocol, Tuple, TypedDict

import discord
from discord import app_commands
from discord.ext import commands

from swarm.core import metrics as default_metrics
from swarm.frontends.discord.discord_interactions import safe_send as default_safe_send
from swarm.frontends.discord.types import SafeSendFunc
from swarm.plugins.base_di import BaseDIClientCog
from swarm.plugins.commands.decorators import background_app_command

# visual separator in a single embed field
SPACER = " • "


class MetricsStats(TypedDict):
    uptime_s: float
    discord_messages_processed: int
    messages_sent: int


class MetricsProtocol(Protocol):
    def get_stats(self) -> MetricsStats: ...
    def format_hms(self, seconds: float) -> str: ...
    def get_cpu_mem(self) -> tuple[str, str]: ...


class Status(BaseDIClientCog):
    def __init__(
        self,
        *,
        discord_bot: commands.Bot,
        metrics_mod: MetricsProtocol | None = None,
        safe_send_func: SafeSendFunc | None = None,
    ) -> None:
        super().__init__(discord_bot)
        self.discord_bot = discord_bot
        if metrics_mod is not None:
            self.metrics = metrics_mod
        else:
            # Wrap module functions in an adapter implementing the protocol
            class _MetricsAdapter(MetricsProtocol):
                def get_stats(self) -> MetricsStats:
                    raw = default_metrics.get_stats()
                    return MetricsStats(
                        uptime_s=float(raw.get("uptime_s", 0.0)),
                        discord_messages_processed=int(raw.get("discord_messages_processed", 0)),
                        messages_sent=int(raw.get("messages_sent", 0)),
                    )

                def format_hms(self, seconds: float) -> str:
                    return default_metrics.format_hms(seconds)

                def get_cpu_mem(self) -> tuple[str, str]:
                    return default_metrics.get_cpu_mem()

            self.metrics = _MetricsAdapter()
        self.safe_send: SafeSendFunc = (
            safe_send_func if safe_send_func is not None else default_safe_send
        )

    @app_commands.command(
        name="status", description="Shows swarm uptime and message counters (owner-only)."
    )
    @app_commands.default_permissions(administrator=True)  # superset of owner
    @background_app_command(defer_ephemeral=True)
    async def status(self, interaction: discord.Interaction) -> None:
        """Reply with wall-clock uptime and swarm traffic counters."""
        s = self.metrics.get_stats()
        uptime_hms = self.metrics.format_hms(float(s["uptime_s"]))
        uptime_hrs = f"{float(s['uptime_s']) / 3600:.1f}"

        # Dynamic counters
        latency_ms = int((self.discord_bot.latency or 0.0) * 1000)
        cpu, mem = self.metrics.get_cpu_mem()
        guilds = len(self.discord_bot.guilds)
        shard_info = (
            f"{(self.discord_bot.shard_id or 0) + 1}/{self.discord_bot.shard_count}"
            if self.discord_bot.shard_count and self.discord_bot.shard_id is not None
            else "n/a"
        )

        # Create one tidy embed instead of a plain string wall
        embed = discord.Embed(
            title="Swarm Status",
            description=f"Uptime: {uptime_hms} ({uptime_hrs} h)",
            colour=discord.Colour.green(),
        )
        embed.add_field(
            name="Traffic",
            value=(
                f"{s['discord_messages_processed']} inbound{SPACER}{s['messages_sent']} outbound"
            ),
            inline=False,
        )

        embed.add_field(
            name="Runtime",
            value=f"CPU {cpu}{SPACER}Memory {mem}",
            inline=False,
        )
        embed.add_field(
            name="Discord",
            value=(f"Latency {latency_ms} ms\nGuilds {guilds}\nShard {shard_info}"),
            inline=False,
        )

        await self.safe_send(interaction, embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Status(discord_bot=bot))
