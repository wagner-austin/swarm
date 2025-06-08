import logging
import discord
from discord import app_commands
from discord.ext import commands  # For commands.Bot, commands.GroupCog
from bot.core.api.proxy_service import ProxyService

log = logging.getLogger(__name__)


class ProxyCog(
    commands.GroupCog,
    group_name="proxy",
    group_description="Manage the TankPit MITM proxy",
):
    def __init__(self, bot: commands.Bot, svc: ProxyService):
        super().__init__()
        self.bot = bot
        self.svc = svc

    @app_commands.command(name="start", description="Start the proxy")
    async def start(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)
        await interaction.followup.send(await self.svc.start())

    @app_commands.command(name="stop", description="Stop the proxy")
    async def stop(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)
        await interaction.followup.send(await self.svc.stop())

    @app_commands.command(name="status", description="Show proxy status")
    async def status(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)
        await interaction.followup.send(self.svc.describe())


async def setup(bot: commands.Bot, proxy_service: ProxyService) -> None:
    """Setup function for the proxy plugin.

    Called by Discord.py when loading the extension.
    """
    await bot.add_cog(ProxyCog(bot, proxy_service))
