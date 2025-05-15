"""
plugins/commands/plugin.py - Plugin management command plugin.
Provides subcommands for listing, enabling, and disabling plugins.
Usage:
  @bot plugin list
  @bot plugin enable <plugin_name>
  @bot plugin disable <plugin_name>
"""

import logging
from typing import List
from plugins.manager import plugin, get_all_plugins, enable_plugin, disable_plugin, disabled_plugins
from core.permissions import ADMIN
from core.state import BotStateMachine
from plugins.commands.subcommand_dispatcher import handle_subcommands, PluginArgError
from plugins.abstract import BasePlugin

@plugin(commands=['plugin'], canonical='plugin', required_role=ADMIN)
class PluginManagerCommand(BasePlugin):
    """
    Manage plugins at runtime with subcommands: list, enable, disable.
    Usage:
      @bot plugin list
      @bot plugin enable <plugin_name>
      @bot plugin disable <plugin_name>
    """
    def __init__(self):
        super().__init__(
            "plugin",
            help_text=(
                "Manage plugins, list, enable, disable.")
        )
        self.subcommands = {
            "list": self._sub_list,
            "enable": self._sub_enable,
            "disable": self._sub_disable
        }

    async def run_command(
        self,
        args: str,
        ctx,
        state_machine,
        **kwargs
    ) -> str:
        usage = (
            "Usage: @bot plugin <list|enable|disable> [args]\n"
            "Examples:\n"
            "  @bot plugin list\n"
            "  @bot plugin enable <plugin_name>\n"
            "  @bot plugin disable <plugin_name>"
        )
        try:
            return handle_subcommands(
                args,
                subcommands=self.subcommands,
                usage_msg=usage,
                unknown_subcmd_msg="Unknown subcommand. See usage: " + usage,
                default_subcommand="default"
            )
        except PluginArgError as e:
            # Use print as fallback if logger is not available (for test context)
            try:
                self.logger.error(f"Argument parsing error in plugin command: {e}", exc_info=True)
            except AttributeError:
                print(f"Argument parsing error in plugin command: {e}")
            return str(e)
        except Exception as e:
            # Use print as fallback if logger is not available (for test context)
            try:
                self.logger.error(f"Unexpected error in plugin command: {e}", exc_info=True)
            except AttributeError:
                print(f"Unexpected error in plugin command: {e}")
            return "An internal error occurred."

    def _sub_list(self, rest: List[str]) -> str:
        info = get_all_plugins()
        if not info:
            return "No plugins found."
        lines = []
        for canonical, pdata in sorted(info.items()):
            if canonical in disabled_plugins:
                lines.append(f"{canonical} (disabled)")
            else:
                lines.append(f"{canonical}")
        return "Installed Plugins:\n" + "\n".join(lines)

    def _sub_enable(self, rest: List[str]) -> str:
        if not rest:
            return "Usage: @bot plugin enable <plugin_name>"
        target = rest[0].lower()
        plugins_dict = get_all_plugins()
        if target not in plugins_dict:
            return f"No plugin found with canonical name '{target}'."
        enable_plugin(target)
        return f"Plugin '{target}' has been enabled."

    def _sub_disable(self, rest: List[str]) -> str:
        if not rest:
            return "Usage: @bot plugin disable <plugin_name>"
        target = rest[0].lower()
        plugins_dict = get_all_plugins()
        if target not in plugins_dict:
            return f"No plugin found with canonical name '{target}'."
        disable_plugin(target)
        return f"Plugin '{target}' has been disabled."

# End of plugins/commands/plugin.py