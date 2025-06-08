from __future__ import annotations

from pathlib import Path
from typing import Any

from selenium.common.exceptions import WebDriverException


class DeadAfterOne:
    """
    First `get()` call succeeds, all subsequent calls raise
    `WebDriverException`.  This kills *only the first* driver instance the
    test creates; the fresh driver that BrowserService spawns afterwards stays
    alive.
    """

    _dead: bool
    _calls: int
    title: str

    def __init__(self) -> None:
        self._dead = False
        self._calls = 0
        self.title = "dummy"

    def get(self, *_args: Any, **_kw: Any) -> None:
        self._calls += 1
        if self._calls > 1:
            self._dead = True
            raise WebDriverException("invalid session id")
        # first navigation succeeds – leave _dead False

    def save_screenshot(self, path: str) -> None:
        Path(path).touch()

    # Added so BrowserSession.close() doesn’t raise AttributeError
    def quit(self) -> None:  # noqa: D401
        return None
