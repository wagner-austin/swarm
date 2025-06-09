# src/bot_core/api/browser/__init__.py
"""
Browser automation API, providing BrowserSession for managing web driver interactions.
"""

from .session import BrowserSession, State
from .session_manager import SessionManager
from .actions import BrowserActions
from . import exceptions

__all__ = [
    "BrowserSession",
    "State",
    "SessionManager",
    "BrowserActions",
    "exceptions",
]
