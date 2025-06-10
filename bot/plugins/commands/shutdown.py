import asyncio
import discord
from discord.ext import commands
from discord import app_commands

from bot.plugins.base_di import BaseDIClientCog


class Shutdown(BaseDIClientCog):
    def __init__(self, bot: commands.Bot) -> None:
        BaseDIClientCog.__init__(self, bot)
        self.bot = bot

    @app_commands.command(
        name="shutdown", description="Cleanly shut the bot down (owner only)."
    )
    async def shutdown(self, interaction: discord.Interaction) -> None:
        """Cleanly shut the bot down (owner-only)."""
        await interaction.response.send_message("Shutting down...")

        bot = interaction.client  # Get the bot instance

        # 1️⃣ terminate auxiliary services via DI container
        try:
            await self.container.proxy_service().aclose()
        except Exception:
            pass

        # Note: Browser cleanup is now handled by /web closeall command
        # Use that command first if you need to specifically close browser instances

        # 2️⃣ finally logout from Discord
        await bot.close()

        # 3️⃣ one extra loop‑tick so CancelledErrors propagate
        await asyncio.sleep(0)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Shutdown(bot))
