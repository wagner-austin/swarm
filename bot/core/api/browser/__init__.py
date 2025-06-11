# __init__ must *not* import runner at import-time – it pulls in
# browser_manager again and explodes during cold-start.  We expose
# WebRunner lazily instead.

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from .engine import BrowserEngine
from .exceptions import BrowserError, InvalidURLError

if TYPE_CHECKING:  # static type-checkers still see the symbol
    from .runner import WebRunner


def __getattr__(name: str) -> Any:  # noqa: D401 – PEP 562 accessor
    if name == "WebRunner":
        module = importlib.import_module(".runner", __name__)
        obj = module.WebRunner
        globals()["WebRunner"] = obj  # cache for next time
        return obj
    raise AttributeError(name)


__all__: list[str] = [
    "BrowserEngine",
    "BrowserError",
    "InvalidURLError",
    "WebRunner",
]
