import asyncio

import discord

from bot.core import metrics
from discord import app_commands
from discord.ext import commands

from bot.browser.runtime import BrowserRuntime
from bot.plugins.base_di import BaseDIClientCog
from bot.utils.discord_interactions import safe_send


class Shutdown(BaseDIClientCog):
    def __init__(self, bot: commands.Bot) -> None:
        BaseDIClientCog.__init__(self, bot)
        self.bot = bot
        self.runtime: BrowserRuntime = bot.container.browser_runtime()  # type: ignore[attr-defined]

    @app_commands.command(name="shutdown", description="Cleanly shut the bot down (owner only).")
    async def shutdown(self, interaction: discord.Interaction) -> None:
        """Shut the bot down (owner-only)."""
        await safe_send(interaction, "📴 Shutting down…")

        bot = interaction.client  # Get the bot instance

        # 1️⃣ terminate auxiliary services via DI container
        try:
            await self.container.proxy_service().aclose()
        except Exception:
            pass

        # 1️⃣.b Close all browser engines
        try:
            await self.runtime.close_all()
        except Exception:
            # Log internally – user sees generic shutdown msg already
            pass

        # 2️⃣ gather stats & send final confirmation then logout
        stats = metrics.get_stats()
        uptime_hms = metrics.format_hms(stats["uptime_s"])
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
        await safe_send(interaction, embed=embed, ephemeral=True)

        await bot.close()

        # 3️⃣ one extra loop‑tick so CancelledErrors propagate
        await asyncio.sleep(0)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Shutdown(bot))
