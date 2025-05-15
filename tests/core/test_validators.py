"""
tests/core/test_validators.py - Tests for the CLI argument validation functions in core/validators.py.
Ensures that allowed CLI flags pass validation and disallowed flags or dangerous characters raise errors.
Includes parameterized tests for partial dangerous patterns.
"""

import pytest
from core.validators import validate_cli_args, CLIValidationError

def test_validate_cli_args_valid():
    # Valid arguments should not raise an error.
    args = ["send", "--message-from-stdin"]
    # Should pass without error.
    validate_cli_args(args)

def test_validate_cli_args_invalid_flag():
    # A flag not in ALLOWED_CLI_FLAGS should trigger a CLIValidationError.
    args = ["-x"]
    with pytest.raises(CLIValidationError) as excinfo:
        validate_cli_args(args)
    assert "Disallowed flag" in str(excinfo.value)

def test_validate_cli_args_dangerous_character():
    # An argument containing dangerous characters should trigger a CLIValidationError.
    args = ["send", "test;rm -rf /"]
    with pytest.raises(CLIValidationError) as excinfo:
        validate_cli_args(args)
    assert "Potentially dangerous character" in str(excinfo.value)

@pytest.mark.parametrize("args,should_raise", [
    (["send", "some safe text"], False),
    (["send", "some;safe"], True),
    (["send", "safe`text"], True),
    (["send", "safe&text"], True),
    (["send", "safe|text"], True),
    (["send", "some safe text;"], True),
    (["send", "cleantext"], False),
])
def test_validate_cli_args_partial_dangerous(args, should_raise):
    """
    Test validate_cli_args with a mix of safe and unsafe patterns.
    Unsafe patterns include semicolons, backticks, ampersands, and vertical bars.
    """
    if should_raise:
        with pytest.raises(CLIValidationError):
            validate_cli_args(args)
    else:
        validate_cli_args(args)

# End of tests/core/test_validators.py