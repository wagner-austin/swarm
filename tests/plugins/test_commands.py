"""
File: tests/plugins/test_commands.py - Integration-level plugin test.
Ensures that the overall plugin registry is loading commands as expected
and that each registered plugin function returns a valid response.

Note: Plugin-specific tests have been moved to their own test_<plugin_name>.py files.
This file no longer tests individual plugin commands in detail; see per-plugin test files.
"""

import pytest
from plugins.manager import load_plugins, get_all_plugins
from core.state import BotStateMachine

@pytest.mark.asyncio
async def test_all_plugin_commands():
    """
    Ensure each registered plugin command can be invoked without errors at an integration level.
    Does NOT test specific plugin behaviors; see dedicated test_<plugin_name>.py files for details.
    """
    load_plugins()
    state_machine = BotStateMachine()
    plugins = get_all_plugins()

    # Only core plugins should be checked
    core_plugins = {"chat", "help", "plugin", "shutdown", "sora explore"}
    for command in core_plugins:
        assert command in plugins, f"Core plugin '{command}' not loaded."
        args = ""
        func = plugins[command]["function"]
        result = func(args, "+dummy", state_machine, msg_timestamp=123)
        if hasattr(result, "__await__"):
            result = await result
        assert isinstance(result, str) and result.strip(), (
            f"Core plugin '{command}' returned an empty or invalid response."
        )

# End of tests/plugins/test_commands.py