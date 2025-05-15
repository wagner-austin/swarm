"""
tests/parsers/test_command_extractor.py - Tests for command extraction functionalities.
This module tests the extraction of commands and arguments from message bodies.
"""

from bot_core.parsers.command_extractor import parse_command_from_body

def test_parse_command_with_prefix():
    body = "@bot register John Doe"
    command, args = parse_command_from_body(body, is_group=False)
    assert command == "register"
    assert args == "John Doe"

def test_parse_command_without_prefix_private():
    body = "test"
    command, args = parse_command_from_body(body, is_group=False)
    # Should work even without prefix in a private chat.
    assert command == "test"
    assert args == ""

def test_parse_command_group_with_prefix():
    body = "@bot help"
    command, args = parse_command_from_body(body, is_group=True)
    assert command == "help"
    assert args == ""

def test_parse_command_invalid():
    body = "@bot invalid_command arg1 arg2"
    command, args = parse_command_from_body(body, is_group=False)
    # Since underscores are not allowed by _validate_command, command should be None.
    assert command is None

# End of tests/parsers/test_command_extractor.py
