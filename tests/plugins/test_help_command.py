"""
File: tests/plugins/test_help_command.py
----------------------------------------
Tests for the 'help' command plugin.
Verifies that the plugin returns a non-empty string and references at least one whitelisted command.
"""

from bot_core.state import BotStateMachine
from bot_plugins.manager import get_plugin, load_plugins
import asyncio

def test_help_command():
    load_plugins()
    state_machine = BotStateMachine()
    help_plugin = get_plugin("help")
    response = help_plugin("", "+dummy", state_machine, msg_timestamp=123)
    if asyncio.iscoroutine(response):
        response = asyncio.get_event_loop().run_until_complete(response)
    assert isinstance(response, str), "help_command did not return a string."
    assert response.strip(), "help_command returned an empty or whitespace-only response."
    # At least one known whitelisted command should appear in the help text:
    assert "info" in response.lower() or "register" in response.lower(), (
        "help_command output does not mention any expected commands."
    )

# End of tests/plugins/test_help_command.py