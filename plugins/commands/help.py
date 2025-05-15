#!/usr/bin/env python
"""
File: plugins/commands/help.py
------------------------------
Summary: Help command plugin. Lists available commands.

Now only shows commands that the user has permission to use, based on their volunteer role.
Focuses on modular, unified, consistent code that facilitates future updates.
"""

from plugins.manager import plugin, get_all_plugins, disabled_plugins
from core.permissions import has_permission, EVERYONE
from core.state import BotStateMachine
from plugins.abstract import BasePlugin

@plugin(["help"], canonical="help", required_role=EVERYONE) 
class HelpPlugin(BasePlugin):
    """
    Help command plugin.
    Lists available commands, filtered by user role.

    Usage:
      @bot help
    """
    def __init__(self):
        super().__init__(
            "help",
            help_text="List available commands."
        )

    async def run_command(
        self,
        args: str,
        ctx,
        state_machine: BotStateMachine,
        **kwargs
    ) -> str:
        usage = "Usage: @bot help"
        user_input = args.strip()

        # If there's extraneous user input, show usage
        if user_input:
            return usage

        try:
            # Determine user's role from ctx
            from core.identity import resolve_role
            user_role = resolve_role(getattr(ctx, 'author', ctx))

            plugins_info = get_all_plugins()
            lines = []

            for canonical, info in sorted(plugins_info.items()):
                help_text = info.get("help_text", "No description")
                required_role = info.get("required_role", "owner")

                # Skip if plugin is disabled
                if canonical in disabled_plugins:
                    lines.append(f"@bot {canonical} (disabled) - {help_text}")
                    continue

                # Skip if not help_visible
                if not info.get("help_visible", True):
                    continue

                # Check user permission for this plugin
                if has_permission(user_role, required_role):
                    lines.append(f"@bot {canonical} - {help_text}")

            return "\n\n".join(lines) if lines else "No commands available."
        except Exception as e:
            # Use print as fallback if logger is not available (for test context)
            try:
                self.logger.error(f"Unexpected error in help command: {e}", exc_info=True)
            except AttributeError:
                print(f"Unexpected error in help command: {e}")
            from plugins.messages import INTERNAL_ERROR
            return INTERNAL_ERROR

# End of plugins/commands/help.py