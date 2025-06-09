import discord
from discord.ext import commands
from discord import app_commands

from bot.core.browser_manager import browser_manager


class BrowserStatus(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="browser_status", description="Show Playwright workers.")
    async def browser_status(self, interaction: discord.Interaction) -> None:
        rows = browser_manager.status_readout()
        if not rows:
            await interaction.response.send_message(
                "No active browser workers.", ephemeral=True
            )
            return

        embed = discord.Embed(title="Browser Workers Status")
        for r in rows:
            status_emoji = "🟢 Idle" if r["idle"] else "🔵 Busy"
            embed.add_field(
                name=f"Channel ID: {r['channel']}",
                value=(
                    f"🗂️ Queue Length: {r['queue_len']}\n"
                    f"{status_emoji}\n"
                    f"📄 Pages Open: {r['pages']}"
                ),
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BrowserStatus(bot))
