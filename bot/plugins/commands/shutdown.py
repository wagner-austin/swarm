import discord
from discord import app_commands
from discord.ext import commands
from discord.ext.commands import is_owner


class Shutdown(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        super().__init__()
        self.bot = bot

    @app_commands.command(
        name="shutdown", description="Cleanly shuts the bot down (owner only)"
    )
    @is_owner()
    async def shutdown(self, interaction: discord.Interaction) -> None:
        """Cleanly shut the bot down (owner-only)."""
        await interaction.response.send_message("Bot is shutting down…", ephemeral=True)
        await interaction.client.close()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Shutdown(bot))
