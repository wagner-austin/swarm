from warnings import warn
from bot_core.validation import CLIValidationError
import re

warn(
    "core.validators is deprecated; import core.validation instead.",
    DeprecationWarning,
    stacklevel=2,
)

"""
core/validators.py
------------------
Utility module for CLI argument validation, plus phone validation.
Ensures phone meets a +digits pattern, or else raises an error.
"""


def validate_phone(number: str) -> None:
    """Validate a phone number using E.164 format. Raise CLIValidationError if invalid."""

    if not re.match(r"^\+[1-9]\d{1,14}$", number):
        raise CLIValidationError("Invalid phone number format")
