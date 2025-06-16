import logging
import discord
from bot.utils.discord_interactions import safe_defer, safe_followup
from bot.plugins.base_di import BaseDIClientCog  # <- move here
from discord import app_commands
from discord.ext import commands  # For commands.Bot, commands.GroupCog

from bot.netproxy.service import ProxyService

logger = logging.getLogger(__name__)


class ProxyCog(
    BaseDIClientCog,
    commands.GroupCog,
    group_name="proxy",
    group_description="Manage the TankPit MITM proxy",
):
    def __init__(self, bot: commands.Bot) -> None:
        commands.GroupCog.__init__(self)
        BaseDIClientCog.__init__(self, bot)

        self.svc: ProxyService = self.container.proxy_service()

    @app_commands.command(name="start", description="Start the proxy")
    async def start(self, interaction: discord.Interaction) -> None:
        await safe_defer(interaction, thinking=True, ephemeral=True)

        await safe_followup(interaction, await self.svc.start())

    @app_commands.command(name="stop", description="Stop the proxy")
    async def stop(self, interaction: discord.Interaction) -> None:
        await safe_defer(interaction, thinking=True, ephemeral=True)
        await safe_followup(interaction, await self.svc.stop())

    @app_commands.command(name="status", description="Show proxy status")
    async def status(self, interaction: discord.Interaction) -> None:
        await safe_defer(interaction, thinking=True, ephemeral=True)
        desc: str = self.svc.describe()
        await safe_followup(
            interaction,
            f"{desc}\n"
            f"📥 in-queue {self.svc.in_q.qsize()}/{self.svc.in_q.maxsize}  "
            f"📤 out-queue {self.svc.out_q.qsize()}/{self.svc.out_q.maxsize}",
        )


async def setup(bot: commands.Bot) -> None:
    """Setup function for the proxy plugin.

    Called by Discord.py when loading the extension.
    Dependencies are injected into the cog via the DI container.
    """
    await bot.add_cog(ProxyCog(bot))
