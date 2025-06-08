from __future__ import annotations

from pathlib import Path
from typing import Any

from selenium.common.exceptions import WebDriverException


class DeadAfterOne:
    _dead: bool
    title: str

    def __init__(self) -> None:
        self._dead = False
        self.title = "dummy"

    def get(self, *_args: Any, **_kw: Any) -> None:
        if self._dead:
            raise WebDriverException("invalid session id")
        self._dead = True  # dies on next access

    def save_screenshot(self, path: str) -> None:
        Path(path).touch()
