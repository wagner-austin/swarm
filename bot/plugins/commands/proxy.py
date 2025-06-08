import logging
from typing import Any  # Import Any
from discord.ext import commands
from ..base import BaseCog
from bot.core.api.proxy_service import ProxyService

log = logging.getLogger(__name__)

_ENTRY_CMD = "proxy"
CMD_START = "start"
CMD_STOP = "stop"
CMD_STATUS = "status"

USAGE = f"""
Manage the TankPit proxy service.

Sub-commands
  {CMD_START}   – start proxy
  {CMD_STOP}    – stop proxy
  {CMD_STATUS}  – show current state
"""


class ProxyCog(BaseCog):
    """Manage the TankPit proxy service.

    Commands to control the proxy service that routes game traffic.
    """

    def __init__(self, bot: commands.Bot, svc: ProxyService) -> None:
        super().__init__(bot)
        self.svc = svc

    @commands.group(name=_ENTRY_CMD, invoke_without_command=True)
    @commands.is_owner()
    async def _grp(self, ctx: commands.Context[Any]) -> None:
        """Manage the TankPit proxy service.

        The proxy service routes game traffic through a controlled pathway.

        Subcommands:
          start   - Start the proxy service
          stop    - Stop the proxy service
          status  - Check if the proxy is running
        """
        await ctx.send(USAGE)

    @_grp.command(name="start")  # type: ignore[arg-type]
    async def _start(self, ctx: commands.Context[Any]) -> None:
        """Start the proxy service.

        Starts routing game traffic through the proxy.

        Usage: !proxy start
        """
        await ctx.send(await self.svc.start())

    @_grp.command(name="stop")  # type: ignore[arg-type]
    async def _stop(self, ctx: commands.Context[Any]) -> None:
        """Stop the proxy service.

        Stops routing game traffic through the proxy.

        Usage: !proxy stop
        """
        await ctx.send(await self.svc.stop())

    @_grp.command(name="status")  # type: ignore[arg-type]
    async def _status(self, ctx: commands.Context[Any]) -> None:
        """Show whether the proxy is running and on which port."""
        await ctx.send(self.svc.describe())


async def setup(bot: commands.Bot, proxy_service: ProxyService) -> None:
    """Setup function for the proxy plugin.

    Called by Discord.py when loading the extension.
    """
    await bot.add_cog(ProxyCog(bot, proxy_service))
