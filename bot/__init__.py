"""
Package bootstrap **plus** a tiny Windows shim that quells the
`PytestUnraisableExceptionWarning: unclosed transport _ProactorBasePipeTransport`
shown at the end of the test‑suite on Windows/PyPI Python >= 3.11.

We do **not** silence the warning with a filter (which would mask real leaks),
but instead patch the offending `__repr__` so that the transport's garbage
collector finaliser no longer raises when the underlying pipe is already
closed – the same approach used by CPython's own `asyncio` in 3.14 dev.
"""

from __future__ import annotations

from importlib import import_module
from types import ModuleType
from typing import List

# ------------------------------------------------------------------+
#  Windows asyncio transport fixes                                  +
# ------------------------------------------------------------------+

try:
    # Import **once**; the module monkey-patches asyncio at import time
    if __import__("sys").platform.startswith("win"):
        import bot.compat.win_asyncio  # noqa: F401  (side-effects only)
except Exception:  # pragma: no cover
    # Safe fallback – bot still works on non-Windows or stub changes
    pass

# ---------------------------------------------------------------------------+
#  Re‑export public sub‑modules                                              +
# ---------------------------------------------------------------------------+

__all__: list[str] = []

for _name in ["core.logger_setup"]:
    mod: ModuleType = import_module(f".{_name}", __name__)
    # Extract the last part of the module name for the global
    simple_name = _name.split(".")[-1]
    globals()[simple_name] = mod
    __all__.append(simple_name)
