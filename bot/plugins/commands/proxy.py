import logging

import discord
from discord import app_commands
from discord.ext import commands  # For commands.Bot, commands.GroupCog

from bot.frontends.discord.discord_interactions import safe_defer, safe_send
from bot.netproxy.service import ProxyService
from bot.plugins.base_di import BaseDIClientCog  # <- move here

logger = logging.getLogger(__name__)


class ProxyCog(
    BaseDIClientCog,
    commands.GroupCog,
    group_name="proxy",
    group_description="Manage the TankPit MITM proxy",
):
    def __init__(
        self,
        bot: commands.Bot,
        proxy_service: ProxyService | None = None,
    ) -> None:
        commands.GroupCog.__init__(self)
        BaseDIClientCog.__init__(self, bot)
        # Allow explicit DI for testing; fall back to container for production
        self.svc: ProxyService = (
            proxy_service if proxy_service is not None else self.container.proxy_service()
        )

    @app_commands.command(name="start", description="Start the proxy")
    async def start(self, interaction: discord.Interaction) -> None:
        await self._start_impl(interaction)

    async def _start_impl(self, interaction: discord.Interaction) -> None:
        await safe_defer(interaction, thinking=True, ephemeral=True)
        await self.svc.start()
        await safe_send(interaction, self.svc.describe())

    @app_commands.command(name="stop", description="Stop the proxy")
    async def stop(self, interaction: discord.Interaction) -> None:
        await self._stop_impl(interaction)

    async def _stop_impl(self, interaction: discord.Interaction) -> None:
        await safe_defer(interaction, thinking=True, ephemeral=True)
        await self.svc.stop()
        await safe_send(interaction, "🛑 Proxy stopped.")

    @app_commands.command(name="status", description="Show proxy status")
    async def status(self, interaction: discord.Interaction) -> None:
        await self._status_impl(interaction)

    async def _status_impl(self, interaction: discord.Interaction) -> None:
        await safe_defer(interaction, thinking=True, ephemeral=True)
        desc: str = self.svc.describe()
        await safe_send(
            interaction,
            f"{desc}\n"
            f"📥 in-queue {self.svc.in_q.qsize()}/{self.svc.in_q.maxsize}  "
            f"📤 out-queue {self.svc.out_q.qsize()}/{self.svc.out_q.maxsize}",
        )


async def setup(bot: commands.Bot) -> None:
    """Set up the proxy plugin.

    Called by Discord.py when loading the extension.
    Dependencies are injected into the cog via the DI container.
    """
    await bot.add_cog(ProxyCog(bot))
