import asyncio
from typing import Any, Callable, Protocol

import discord
from discord import app_commands
from discord.ext import commands

from bot.frontends.discord.discord_interactions import safe_send
from bot.frontends.discord.discord_owner import get_owner
from bot.plugins.base_di import BaseDIClientCog


class MetricsProtocol(Protocol):
    def get_stats(self) -> dict[str, Any]: ...
    def format_hms(self, seconds: float) -> str: ...


class Shutdown(BaseDIClientCog):
    def __init__(
        self,
        bot: commands.Bot,
        lifecycle: Any = None,
        metrics_mod: MetricsProtocol | None = None,
        get_owner_func: Callable[[commands.Bot], Any] | None = None,
        safe_send_func: Callable[..., Any] | None = None,
    ) -> None:
        BaseDIClientCog.__init__(self, bot)
        self.bot = bot
        # Allow DI for testing
        import bot.core.metrics as default_metrics
        from bot.frontends.discord.discord_interactions import safe_send as default_safe_send
        from bot.frontends.discord.discord_owner import get_owner as default_get_owner

        self.metrics = metrics_mod if metrics_mod is not None else default_metrics
        self.get_owner = get_owner_func if get_owner_func is not None else default_get_owner
        self.safe_send = safe_send_func if safe_send_func is not None else default_safe_send
        # DI for lifecycle, fallback to bot.lifecycle for production
        self.lifecycle = lifecycle if lifecycle is not None else getattr(bot, "lifecycle", None)

    @app_commands.command(name="shutdown", description="Cleanly shut the bot down (owner only).")
    async def shutdown(self, interaction: discord.Interaction) -> None:
        await self._shutdown_impl(interaction)

    async def _shutdown_impl(self, interaction: discord.Interaction) -> None:
        try:
            owner = await self.get_owner(self.bot)
        except RuntimeError:
            await self.safe_send(interaction, "❌ Could not resolve bot owner.", ephemeral=True)
            return

        if interaction.user.id != owner.id:
            await self.safe_send(interaction, "❌ Owner only.", ephemeral=True)
            return
        await self.safe_send(interaction, "📴 Shutting down…")

        # 1️⃣ Auxiliary services are shut down by the bot's lifecycle handler.

        # 2️⃣ gather stats & send final confirmation then logout
        stats = self.metrics.get_stats()
        uptime_hms = self.metrics.format_hms(stats["uptime_s"])
        uptime_hrs = f"{stats['uptime_s'] / 3600:.1f}"
        SPACER = " │ "
        embed = discord.Embed(
            title="Shutdown complete",
            description=f"⏱️ **{uptime_hms}** (≈ {uptime_hrs} h)",
            colour=discord.Colour.red(),
        )
        embed.add_field(
            name="Traffic",
            value=(
                f"📨 {stats['discord_messages_processed']} in{SPACER}✉️ {stats['messages_sent']} out"
            ),
            inline=False,
        )
        await self.safe_send(interaction, embed=embed, ephemeral=True)

        # Call canonical shutdown via lifecycle
        if self.lifecycle is not None:
            await self.lifecycle.shutdown(signal_name="command")
        else:
            # Fallback: close bot directly (should not happen in production)
            await interaction.client.close()

        # 3️⃣ one extra loop‑tick so CancelledErrors propagate
        await asyncio.sleep(0)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Shutdown(bot))
