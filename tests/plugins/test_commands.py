"""
File: tests/plugins/test_commands.py - Integration-level plugin test.
Ensures that the overall plugin registry is loading commands as expected
and that each registered plugin function returns a valid response.

Note: Plugin-specific tests have been moved to their own test_<plugin_name>.py files.
This file no longer tests individual plugin commands in detail; see per-plugin test files.
"""

import pytest
from plugins.manager import get_all_plugins
from core.state import BotStateMachine

@pytest.mark.asyncio
async def test_all_plugin_commands():
    """
    Ensure each registered plugin command can be invoked without errors at an integration level.
    Does NOT test specific plugin behaviors; see dedicated test_<plugin_name>.py files for details.
    """
    state_machine = BotStateMachine()
    plugins = get_all_plugins()

    # Some commands may return empty responses if no data is present; these are allowed here.
    allowed_empty = {"volunteer status"}

    for command, entry in plugins.items():
        args = ""
        func = entry["function"]
        result = func(args, "+dummy", state_machine, msg_timestamp=123)
        if hasattr(result, "__await__"):
            # If it's async, await it
            result = await result

        # For commands that are not known to allow empty, ensure they return a non-empty string
        if command not in allowed_empty:
            assert isinstance(result, str) and result.strip(), (
                f"Plugin '{command}' returned an empty or invalid response at integration level test."
            )

# End of tests/plugins/test_commands.py