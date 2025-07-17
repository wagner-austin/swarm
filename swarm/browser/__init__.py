"""Browser package bootstrap.

Only re-exports thin helpers; the central control surface is
:pydata:`swarm.browser.runtime.runtime`."""

from .engine import BrowserEngine
from .exceptions import BrowserError, InvalidURLError

# WebRunner has been removed – use `swarm.browser.runtime` directly.


__all__: list[str] = [
    "BrowserEngine",
    "BrowserError",
    "InvalidURLError",
]
