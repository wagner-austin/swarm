"""
File: tests/plugins/test_plugin_error_states.py
-----------------------------------------------
Plugin error state tests. Covers a plugin that raises an unhandled exception,
and plugins that return non-string results (lists, integers, etc.).
"""

import pytest
import logging
from managers.message.message_dispatcher import dispatch_message
from parsers.message_parser import ParsedMessage
from plugins.manager import plugin_registry, alias_mapping, clear_plugins
from core.state import BotStateMachine
from managers.volunteer_manager import VOLUNTEER_MANAGER

@pytest.fixture
def dummy_logger(caplog):
    """
    A fixture to capture logs for validation.
    """
    caplog.set_level(logging.WARNING, logger="managers.message.message_dispatcher")
    return caplog

@pytest.fixture
def dummy_state_machine():
    return BotStateMachine()

def test_plugin_returning_non_string(dummy_logger, dummy_state_machine):
    """
    Dynamically register a plugin that returns a list instead of a string.
    Confirm it logs a warning about non-string results and returns an empty string.
    """
    clear_plugins()

    def return_list(args, sender, state_machine, msg_timestamp=None):
        return ["This", "is", "a", "list"]

    alias_mapping["nonstring"] = "nonstring"
    plugin_registry["nonstring"] = {
        "function": return_list,
        "aliases": ["nonstring"],
        "help_visible": True,
    }

    parsed = ParsedMessage(
        sender="+9999999999",
        body="@bot nonstring",
        timestamp=123,
        group_id=None,
        reply_to=None,
        message_timestamp=None,
        command="nonstring",
        args=""
    )
    try:
        response = dispatch_message(parsed, parsed.sender, dummy_state_machine,
                                    volunteer_manager=VOLUNTEER_MANAGER, msg_timestamp=123, logger=logging.getLogger())
        assert response == "", "Expected empty string due to non-string return."
        logs = dummy_logger.text
        assert "returned a non-string result" in logs.lower()
    finally:
        alias_mapping.pop("nonstring", None)
        plugin_registry.pop("nonstring", None)

def test_plugin_raising_exception(dummy_logger, dummy_state_machine):
    """
    Dynamically register a plugin that raises an exception. Confirm dispatch_message
    returns the 'internal error' message and logs an exception.
    """
    clear_plugins()

    def explode_plugin(args, sender, state_machine, msg_timestamp=None):
        raise RuntimeError("Boom!")

    alias_mapping["explode"] = "explode"
    plugin_registry["explode"] = {
        "function": explode_plugin,
        "aliases": ["explode"],
        "help_visible": True,
    }

    parsed = ParsedMessage(
        sender="+9999999999",
        body="@bot explode",
        timestamp=123,
        group_id=None,
        reply_to=None,
        message_timestamp=None,
        command="explode",
        args=""
    )
    try:
        response = dispatch_message(parsed, parsed.sender, dummy_state_machine,
                                    volunteer_manager=VOLUNTEER_MANAGER, msg_timestamp=123, logger=logging.getLogger())
        assert "An internal error occurred" in response
        logs = dummy_logger.text
        assert "Error executing plugin for command 'explode'" in logs
    finally:
        alias_mapping.pop("explode", None)
        plugin_registry.pop("explode", None)

def test_plugin_returning_int(dummy_logger, dummy_state_machine):
    """
    Dynamically register a plugin that returns an integer instead of a string.
    Confirm it logs a warning about non-string results and returns an empty string.
    """
    clear_plugins()

    def return_int(args, sender, state_machine, msg_timestamp=None):
        return 42

    alias_mapping["returnint"] = "returnint"
    plugin_registry["returnint"] = {
        "function": return_int,
        "aliases": ["returnint"],
        "help_visible": True,
    }

    parsed = ParsedMessage(
        sender="+9999999999",
        body="@bot returnint",
        timestamp=123,
        group_id=None,
        reply_to=None,
        message_timestamp=None,
        command="returnint",
        args=""
    )
    try:
        response = dispatch_message(parsed, parsed.sender, dummy_state_machine,
                                    volunteer_manager=VOLUNTEER_MANAGER, msg_timestamp=123, logger=logging.getLogger())
        assert response == "", "Expected empty string due to non-string return."
        logs = dummy_logger.text
        assert "returned a non-string result" in logs.lower()
    finally:
        alias_mapping.pop("returnint", None)
        plugin_registry.pop("returnint", None)

# End of tests/plugins/test_plugin_error_states.py