import asyncio
import discord
from discord.ext import commands
from discord import app_commands

from bot.plugins.base_di import BaseDIClientCog
from bot.core.browser_manager import browser_manager


class Shutdown(BaseDIClientCog):
    def __init__(self, bot: commands.Bot) -> None:
        BaseDIClientCog.__init__(self, bot)
        self.bot = bot

    @app_commands.command(
        name="shutdown", description="Cleanly shut the bot down (owner only)."
    )
    async def shutdown(self, interaction: discord.Interaction) -> None:
        """Cleanly shut the bot down (owner-only)."""
        await interaction.response.send_message("Shutting down ...")

        bot = interaction.client  # Get the bot instance

        # 1️⃣ stop accepting new work
        await browser_manager.close_all()

        # 2️⃣ terminate auxiliary services via DI container
        try:
            await self.container.proxy_service().aclose()
        except Exception:
            pass

        # 3️⃣ finally logout from Discord
        await bot.close()

        # 4️⃣ one extra loop‑tick so CancelledErrors propagate
        await asyncio.sleep(0)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Shutdown(bot))
