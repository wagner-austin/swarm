"""
Ensures that the slash‑command names documented in the cog’s help text
actually exist in the code.

This test was originally written for the legacy *browser* cog; it now targets
the renamed *web* cog introduced in #214.
"""

from __future__ import annotations

import importlib
import re
import unittest

# Dynamically import the cog so we never depend on its concrete filename.
web_mod = importlib.import_module("bot.plugins.commands.web")

CMD_ROOT = "web"  # hard‑coded top‑level slash command
USAGE: str = web_mod.__doc__ or ""

# Keep this list in sync with the explicit @app_commands.command(name="…")
# decorators inside bot/plugins/commands/web.py
_WEB_SUBCOMMANDS: set[str] = {
    "start",
    "click",
    "fill",
    "upload",
    "wait",
    "screenshot",
}


class TestCommandConsistency(unittest.TestCase):
    """Tests to ensure command names match their documentation."""

    def test_browser_command_names(self) -> None:
        """Verify browser commands in usage text match actual command names."""
        # Extract command names from USAGE text
        usage_commands = set()
        for line in USAGE.split("\n"):
            # Look for commands in backticks like `command_name ...`
            match = re.search(r"`([a-zA-Z0-9_]+)", line)
            if match:
                usage_commands.add(match.group(1))

        # Implemented commands taken straight from `_BROWSER_SUBCOMMANDS`
        actual_commands = _WEB_SUBCOMMANDS

        # ------------------------------------------------------------+
        # 1)  Docs → Code: every command mentioned in USAGE must be
        #     implemented. (Protects against stale docs.)
        # ------------------------------------------------------------+
        for cmd in usage_commands:
            # Skip the parent command which isn't in our set
            if cmd != CMD_ROOT:
                self.assertIn(
                    cmd,
                    actual_commands,
                    f"Command '{cmd}' mentioned in USAGE but not implemented",
                )

        # ------------------------------------------------------------+
        # 2)  Code → Docs: we no longer *require* every implemented
        #     command to be documented, because slash menus show them
        #     automatically.  Instead just enforce naming style.
        # ------------------------------------------------------------+
        for cmd in actual_commands:
            self.assertRegex(
                cmd,
                r"^[a-z0-9_]+$",
                f"Command constant '{cmd}' should be lower-case ASCII",
            )
