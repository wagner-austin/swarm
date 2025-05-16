#!/usr/bin/env python
"""
core/validation.py - Pure helper functions for validation (no domain rules).
"""

import re
from bot_plugins.constants import DANGEROUS_PATTERN

# Precompile the dangerous pattern regex
DANGEROUS_REGEX = re.compile(DANGEROUS_PATTERN)


class CLIValidationError(Exception):
    """Custom exception for CLI validation errors."""

    pass


# Add any new pure validation helpers here
