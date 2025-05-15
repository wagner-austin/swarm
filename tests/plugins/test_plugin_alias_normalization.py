"""
File: tests/plugins/test_plugin_alias_normalization.py
------------------------------------------------------
Tests for plugin alias normalization.
Verifies that duplicate aliases (even with different formatting) raise an error and that aliases are normalized.
Also tests that substring/prefix aliases like "info" vs. "information" do not conflict under exact matching rules.
"""

import pytest
from bot_plugins.manager import plugin, clear_plugins, plugin_registry, alias_mapping


def test_substring_alias_coexistence():
    """
    Ensure that registering plugins with aliases where one is a substring/prefix of the other
    (e.g., 'info' vs. 'information') does not cause incorrect conflicts or matches.
    """
    clear_plugins()

    # Plugin A: alias 'info'
    @plugin(commands=["info"], canonical="info_cmd")
    def plugin_info(args, sender, state_machine, msg_timestamp=None):
        return "Invoked info plugin"

    # Plugin B: alias 'information'
    @plugin(commands=["information"], canonical="information_cmd")
    def plugin_information(args, sender, state_machine, msg_timestamp=None):
        return "Invoked information plugin"

    # Confirm both aliases are registered
    assert "info_cmd" in plugin_registry
    assert "information_cmd" in plugin_registry
    assert "info" in alias_mapping
    assert "information" in alias_mapping

    # Check that they map to different canonical commands
    assert alias_mapping["info"] == "info_cmd"
    assert alias_mapping["information"] == "information_cmd"

    # Further test: call each alias to ensure we get the correct function
    func_info = plugin_registry[alias_mapping["info"]]["function"]
    func_information = plugin_registry[alias_mapping["information"]]["function"]

    # Mock arguments
    import asyncio
    info_result = func_info("", "+1234", None)
    if asyncio.iscoroutine(info_result):
        info_result = asyncio.get_event_loop().run_until_complete(info_result)
    information_result = func_information("", "+5678", None)
    if asyncio.iscoroutine(information_result):
        information_result = asyncio.get_event_loop().run_until_complete(information_result)

    assert "Invoked info plugin" in info_result
    assert "Invoked information plugin" in information_result

    # Cleanup
    clear_plugins()

# End of tests/plugins/test_plugin_alias_normalization.py