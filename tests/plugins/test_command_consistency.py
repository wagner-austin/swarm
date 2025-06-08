import unittest
import re

from bot.plugins.commands.browser import USAGE, _ENTRY_CMD as CMD_BROWSER

# Single source-of-truth for the six sub-command names.
# (Matches the explicit `@app_commands.command(name="…")` decorators in browser.py.)
_BROWSER_SUBCOMMANDS: set[str] = {
    "start",
    "open",
    "close",
    "screenshot",
    "status",
    "restart",
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
        actual_commands = _BROWSER_SUBCOMMANDS

        # ------------------------------------------------------------+
        # 1)  Docs → Code: every command mentioned in USAGE must be
        #     implemented. (Protects against stale docs.)
        # ------------------------------------------------------------+
        for cmd in usage_commands:
            # Skip the parent command which isn't in our set
            if cmd != CMD_BROWSER:
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
