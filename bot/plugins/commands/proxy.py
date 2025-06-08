import logging
from typing import Any  # Import Any
from discord.ext import commands
from ..base import BaseCog
from bot.core.api.proxy_service import ProxyService

log = logging.getLogger(__name__)
USAGE = "`!proxy start|stop|status`"


class ProxyCog(BaseCog):
    """Cog for managing the TankPit proxy service."""

    def __init__(self, bot: commands.Bot, svc: ProxyService) -> None:
        super().__init__(bot)
        self.svc = svc

    # group definition
    @commands.group(name="proxy", invoke_without_command=True)
    @commands.is_owner()
    async def _grp(self, ctx: commands.Context[Any]) -> None:
        await ctx.send(USAGE)

    @_grp.command(name="start")  # type: ignore[arg-type]
    async def _start(self, ctx: commands.Context[Any]) -> None:
        await ctx.send(await self.svc.start())

    @_grp.command(name="stop")  # type: ignore[arg-type]
    async def _stop(self, ctx: commands.Context[Any]) -> None:
        await ctx.send(await self.svc.stop())

    @_grp.command(name="status")  # type: ignore[arg-type]
    async def _status(self, ctx: commands.Context[Any]) -> None:
        await ctx.send("running" if self.svc.is_running() else "stopped")


async def setup(bot: commands.Bot, proxy_service: ProxyService) -> None:
    await bot.add_cog(ProxyCog(bot, proxy_service))
