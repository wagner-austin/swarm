"""
File: tests/plugins/test_commands.py - Integration-level plugin test.
Ensures that the overall plugin registry is loading commands as expected
and that each registered plugin function returns a valid response.

Note: Plugin-specific tests have been moved to their own test_<plugin_name>.py files.
This file no longer tests individual plugin commands in detail; see per-plugin test files.
"""

import pytest
from bot_plugins.manager import load_plugins, get_all_plugins
from bot_core.state import BotStateMachine

@pytest.mark.asyncio
async def test_all_plugin_commands(async_db):
    """
    Ensure each registered plugin command can be invoked without errors at an integration level.
    Does NOT test specific plugin behaviors; see dedicated test_<plugin_name>.py files for details.
    """
    load_plugins()
    state_machine = BotStateMachine()
    plugins = get_all_plugins()

    # Only core plugins should be checked
    core_plugins = {"chat", "help", "plugin", "shutdown", "browser"}
    for command in core_plugins:
        assert command in plugins, f"Core plugin '{command}' not loaded."
        args = ""
        func = plugins[command]["function"]
        result = await func(args, "+dummy", state_machine, msg_timestamp=123)
        # result is now a string; do not await again
        assert isinstance(result, str) and result.strip(), (
            f"Core plugin '{command}' returned an empty or invalid response."
        )

# End of tests/plugins/test_commands.py