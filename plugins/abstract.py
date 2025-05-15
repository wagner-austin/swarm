"""
plugins/abstract.py
-------------------
BasePlugin class for plugin architecture. Defines an abstract base class with a standard
interface for all plugin classes.

Stable Plugin API for Community Developers:
-------------------------------------------
1) Create a new file in `plugins/commands/` (e.g., `myplugin.py`).
2) Import and subclass `BasePlugin` if you need an object-oriented approach, or just
   use the `@plugin` decorator from `plugins.manager`.
3) Decorate your command function/class with `@plugin("mycmd", canonical="mycmd")`.
   - `commands` can be a string or list of strings (aliases).
   - `canonical` is the primary name of your command (required if multiple aliases).
4) Implement your logic in `run_command(args, sender, state_machine, msg_timestamp)`.
5) If you have subcommands, define them in a dictionary. For usage, see `subcommand_dispatcher`.
6) Test by running the bot and typing `@bot mycmd`.

This API aims to remain stable so your external plugin code won't break on minor updates.
"""

from abc import ABC, abstractmethod
from typing import Optional
from core.state import BotStateMachine

class BasePlugin(ABC):
    def __init__(self, command_name: str, help_text: str = ""):
        self.command_name = command_name
        self.help_text = help_text
        self.subcommands = {}

    @abstractmethod
    def run_command(
        self,
        args: str,
        ctx,
        state_machine: BotStateMachine,
        msg_timestamp: Optional[int] = None
    ) -> str:
        """
        Main entrypoint for plugin execution.

        Args:
            args (str): Arguments passed to the plugin command.
            ctx: The raw Discord context (normally a discord.Message).
            state_machine: The bot's state machine instance.
            msg_timestamp: Optional message timestamp.

        Returns:
            str: The plugin's response message.
        """
        pass

# End of plugins/abstract.py