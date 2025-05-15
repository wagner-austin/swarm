#!/usr/bin/env python
"""
plugins/commands/shutdown.py
----------------------------
Summary: Shutdown command plugin. Shuts down the bot.
Usage:
  @bot shutdown
"""
 
import logging
from typing import List, Optional
from bot_plugins.manager import plugin
from bot_core.permissions import OWNER
from bot_core.state import BotStateMachine
from bot_plugins.commands.subcommand_dispatcher import handle_subcommands
from bot_plugins.abstract import BasePlugin
from bot_plugins.messages import BOT_SHUTDOWN, INTERNAL_ERROR
from bot_plugins.subcommand_mixin import SubcommandPluginMixin


@plugin(['shutdown', 'shut down'], canonical='shutdown', required_role=OWNER)
class ShutdownPlugin(SubcommandPluginMixin, BasePlugin):
    """
    Shut down the bot.
    Usage:
      @bot shutdown
    """
    def __init__(self):
        super().__init__(
            "shutdown",
            help_text="Shut down the program."
        )
        self.subcommands = {"default": self._default_subcmd}
        self.logger = logging.getLogger(__name__)
        self.state_machine: Optional[BotStateMachine] = None

    async def run_command(
        self,
        args: str,
        ctx,
        state_machine,
        **kwargs
    ) -> str:
        self.state_machine = state_machine
        return await self.dispatch_subcommands(
            args,
            subcommands=self.subcommands,
            usage_msg="Usage: @bot shutdown",
            default_subcommand="default",
        )
    
    def _default_subcmd(self, rest: List[str]) -> str:
        if rest:
            return "Usage: @bot shutdown"
        if self.state_machine:
            self.state_machine.shutdown()
        return BOT_SHUTDOWN

# End of plugins/commands/shutdown.py