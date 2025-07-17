"""
Browser‑subsystem exception types.

Keeping them in their own small module avoids import cycles and lets
call‑sites depend on a single import path.
"""


class BrowserError(Exception):
    """Base‑class for all browser‑layer problems."""

    pass


class InvalidURLError(BrowserError, ValueError):
    """Raised when a user‑supplied URL does not pass validation."""

    pass
