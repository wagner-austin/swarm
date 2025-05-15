#!/usr/bin/env python
"""
plugins/commands/info.py
------------------------
Summary: Info command plugin. Displays bot information.
Usage:
  @bot info
"""

from bot_plugins.manager import plugin
from bot_core.permissions import EVERYONE
from bot_plugins.abstract import BasePlugin
from bot_plugins.messages import INFO_USAGE, INFO_TEXT, INTERNAL_ERROR

@plugin(["info"], canonical="info", required_role=EVERYONE)
class InfoPlugin(BasePlugin):
    """
    Display bot information.

    Usage:
      @bot info
    """
    def __init__(self):
        super().__init__(
            "info",
            help_text="Display information about our cause."
        )

    async def run_command(
        self,
        args: str,
        ctx,
        state_machine,
        **kwargs
    ) -> str:
        usage = INFO_USAGE
        user_input = args.strip()

        # If there's extraneous user input, show usage
        if user_input:
            return usage

        try:
            return INFO_TEXT
        except Exception as e:
            self.logger.error(f"Unexpected error in info command: {e}", exc_info=True)
            return INTERNAL_ERROR

# End of plugins/commands/info.py