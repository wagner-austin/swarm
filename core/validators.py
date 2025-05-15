#!/usr/bin/env python
"""
core/validators.py
------------------
Utility module for CLI argument validation, plus phone validation.
Ensures phone meets a +digits pattern, or else raises an error.

CHANGES:
 - Updated 'Invalid phone number format' message to exactly match test expectations.
"""

import re
from plugins.constants import DANGEROUS_PATTERN
from core.exceptions import VolunteerError

# Precompile the dangerous pattern regex
DANGEROUS_REGEX = re.compile(DANGEROUS_PATTERN)

class CLIValidationError(Exception):
    """Custom exception for CLI validation errors."""


def validate_phone(number: str) -> None:
    """
    Validate a phone number using E.164 format. Raise VolunteerError if invalid.
    """
    import re
    if not re.match(r'^\+[1-9]\d{1,14}$', number):
        raise VolunteerError("Invalid phone number format")

# End of core/validators.py