#!/usr/bin/env python
"""
core/validation.py - Pure helper functions for validation (no domain rules).
"""

import re

# -- moved here to avoid circular dependency & stale file --
DANGEROUS_PATTERN = r"[;&|`]"
# urllib.parse is used by bot.utils.urls.looks_like_web_url

# Precompile the dangerous pattern regex
DANGEROUS_REGEX = re.compile(DANGEROUS_PATTERN)


class CLIValidationError(Exception):
    """Custom exception for CLI validation errors."""

    pass


# Web-URL helpers are now in bot.utils.urls
