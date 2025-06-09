"""
Custom exceptions for the BrowserService and related browser operations.
"""


class BrowserServiceError(Exception):
    """Base class for exceptions raised by the BrowserService."""

    pass


class BrowserInitializationError(BrowserServiceError):
    """Raised when the browser driver fails to initialize."""

    pass


class BrowserStateError(BrowserServiceError):
    """Raised when an operation is attempted in an inappropriate browser state."""

    pass


class NavigationError(BrowserServiceError):
    """Raised when a browser navigation operation fails."""

    pass


class ScreenshotError(BrowserServiceError):
    """Raised when taking a screenshot fails."""

    pass


class InvalidURLError(BrowserServiceError, ValueError):
    """Raised when a URL is considered invalid for browser operations.
    Inherits from ValueError for compatibility with existing checks if needed.
    """

    pass
