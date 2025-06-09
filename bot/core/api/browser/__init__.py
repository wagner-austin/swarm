# src/bot_core/api/browser/__init__.py
"""
Browser automation API, providing BrowserSession for managing web driver interactions.
"""

from .session import BrowserSession, State

__all__ = ["BrowserSession", "State"]
