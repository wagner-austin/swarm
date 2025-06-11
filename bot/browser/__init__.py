"""bot.browser – public Playwright subsystem façade.

This namespace *re-exports* all objects from the original implementation that
still lives under ``bot.core.api.browser``.  External code **must** only import
from :pymod:`bot.browser` moving forward; the old path remains for backwards
compatibility but will be removed in a future release.
"""
from __future__ import annotations

import importlib
import sys
from types import ModuleType
from typing import Final, List

_BACKEND_PACKAGE: Final[str] = "bot.core.api.browser"
_SUBMODULES: Final[List[str]] = [
    "actions",
    "command",
    "engine",
    "exceptions",
    "registry",
    "runner",
    "signals",
    "worker",
]

# ---------------------------------------------------------------------------+
#  Dynamically alias backend sub-modules                                      +
# ---------------------------------------------------------------------------+

for _name in _SUBMODULES:
    _full_backend = f"{_BACKEND_PACKAGE}.{_name}"
    _alias = f"{__name__}.{_name}"
    # Import backend module and register it under the new alias so that
    # ``import bot.browser.runner`` works transparently.
    mod: ModuleType = importlib.import_module(_full_backend)
    sys.modules[_alias] = mod

# ---------------------------------------------------------------------------+
#  Re-export public surface                                                   +
# ---------------------------------------------------------------------------+

from bot.core.api.browser.engine import BrowserEngine  # noqa: E402  (re-export)
from bot.core.api.browser.runner import WebRunner  # noqa: E402
from bot.core.api.browser.exceptions import BrowserError, InvalidURLError  # noqa: E402

__all__: list[str] = [
    "BrowserEngine",
    "WebRunner",
    "BrowserError",
    "InvalidURLError",
]
