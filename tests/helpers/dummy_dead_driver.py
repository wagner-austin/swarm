from pathlib import Path
from selenium.common.exceptions import WebDriverException

class DeadAfterOne:
    def __init__(self):
        self._dead = False
        self.title = "dummy"

    def get(self, *_args, **_kw):
        if self._dead:
            raise WebDriverException("invalid session id")
        self._dead = True           # dies on next access

    def save_screenshot(self, path: str) -> None:
        Path(path).touch()
