#!/usr/bin/env python
"""
tests/core/test_constants.py – Test for core/constants.py: Verify constant definitions.
"""
import re
import plugins.constants as constants

def test_skip_values_is_set():
    assert isinstance(constants.SKIP_VALUES, set)
    assert "skip" in constants.SKIP_VALUES

def test_allowed_cli_flags_is_set():
    assert isinstance(constants.ALLOWED_CLI_FLAGS, set)
    assert "send" in constants.ALLOWED_CLI_FLAGS

def test_dangerous_pattern_valid():
    pattern = constants.DANGEROUS_PATTERN
    regex = re.compile(pattern)
    test_string = "test; rm -rf /"
    assert regex.search(test_string) is not None

# End of tests/core/test_constants.py