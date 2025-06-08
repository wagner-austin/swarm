import unittest
import re
from bot.plugins.commands.browser import (
    USAGE,
    CMD_BROWSER,
    CMD_START,
    CMD_OPEN,
    CMD_CLOSE,
    CMD_SCREENSHOT,
    CMD_STATUS,
    CMD_RESTART,
)


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

        # Get the defined command constants
        actual_commands = {
            CMD_START,
            CMD_OPEN,
            CMD_CLOSE,
            CMD_SCREENSHOT,
            CMD_STATUS,
            CMD_RESTART,
        }

        # Verify all documented commands exist in actual commands
        for cmd in usage_commands:
            # Skip the parent command which isn't in our set
            if cmd != CMD_BROWSER:
                self.assertIn(
                    cmd,
                    actual_commands,
                    f"Command '{cmd}' mentioned in USAGE but not implemented",
                )

        # Verify all implemented commands are documented
        for cmd in actual_commands:
            self.assertIn(
                cmd,
                usage_commands,
                f"Command '{cmd}' implemented but not mentioned in USAGE",
            )
