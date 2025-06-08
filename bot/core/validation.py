#!/usr/bin/env python
"""
core/validation.py - Pure helper functions for validation (no domain rules).
"""

import re
from bot.plugins.constants import DANGEROUS_PATTERN
from urllib.parse import urlparse

# Precompile the dangerous pattern regex
DANGEROUS_REGEX = re.compile(DANGEROUS_PATTERN)


class CLIValidationError(Exception):
    """Custom exception for CLI validation errors."""

    pass


# ---------------------------------------------------------------------------+
# Web-URL helpers                                                            #
# ---------------------------------------------------------------------------+


def looks_like_web_url(raw: str) -> bool:
    """
    Very cheap sanity-check so we don't even try to launch Chrome for obviously
    bad input such as "qwasd" or "ftp://…".

    Rules (good enough for a Discord command):
      • scheme must be http/https (if missing we'll add https later)
      • there must be a *netloc* ( e.g. example.com )
      • the netloc contains either a dot ("example.com") **or** is "localhost"
    """
    from .api.browser.session import _normalise_url  # local import avoids cycles

    url = _normalise_url(raw)
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        return False
    if not p.netloc:
        return False
    if "." not in p.netloc and p.netloc.lower() != "localhost":
        return False
    return True
