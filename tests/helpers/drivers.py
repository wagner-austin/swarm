from __future__ import annotations

from pathlib import Path
from typing import Any


class _BaseStub:
    current_url: str = "about:blank"

    # Accept *any* ctor signature the real driver factory passes through
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    # ----- Selenium‑like API -------------------------------------------
    def get(self, url: str, *_a: Any, **_kw: Any) -> None:
        self.current_url = url

    def save_screenshot(self, path: str) -> bool:
        Path(path).touch()
        return True

    def quit(self) -> None: ...
    def close(self) -> None: ...


class DummyDriver(_BaseStub):
    """Always alive – use for happy‑path tests."""


class DeadAfterN(_BaseStub):
    """
    Stays alive for *n* successful ``get`` calls, then raises the given
    *exception_cls* (default: ``WebDriverException``) on every further call.
    """

    def __init__(self, n: int = 1, exception_cls: type[Exception] | None = None):
        from selenium.common.exceptions import WebDriverException

        self._limit = n
        self._calls = 0
        self._exc = exception_cls or WebDriverException

    def get(self, url: str, *_a: Any, **_kw: Any) -> None:  # noqa: D401
        self._calls += 1
        if self._calls > self._limit:
            raise self._exc("invalid session id (stub)")
        super().get(url, *_a, **_kw)


# Re‑export for convenience
__all__ = ["DummyDriver", "DeadAfterN"]
