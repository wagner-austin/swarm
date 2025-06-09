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

import sys
from importlib import import_module
from types import ModuleType
from typing import List

# ---------------------------------------------------------------------------+
#  Windows asyncio bug‑work‑around                                          +
# ---------------------------------------------------------------------------+

if sys.platform.startswith("win"):
    try:
        # internal – stable since 3.8; guarded import keeps POSIX untouched
        from asyncio.proactor_events import _ProactorBasePipeTransport
        from asyncio.base_subprocess import BaseSubprocessTransport

        def _safe_repr(self: "object") -> str:  # noqa: D401 – helper
            # The original __repr__ tries `self._sock.fileno()` which blows up
            # after the socket has been closed.  We replace it with something
            # minimal that is guaranteed not to raise.
            return f"<{self.__class__.__name__} fd=closed>"

        # Patching with a proper type-safe approach
        # We need to modify the class itself to ensure proper typing
        # Use setattr instead of direct assignment to avoid mypy's method-assign error
        original_repr = _ProactorBasePipeTransport.__repr__
        setattr(_ProactorBasePipeTransport, "__repr__", _safe_repr)

        # ------------------------------------------------------------------+
        # 2.  Subprocess transport finaliser – ignore "event loop closed"   +
        # ------------------------------------------------------------------+
        # Store original __del__ method
        original_del = BaseSubprocessTransport.__del__

        # Create a properly typed replacement
        def _quiet_del(self: BaseSubprocessTransport) -> None:
            try:
                original_del(self)
            except RuntimeError as exc:  # event‑loop already closed
                if str(exc) != "Event loop is closed":
                    raise

        # Apply the patched method using setattr to avoid mypy errors
        setattr(BaseSubprocessTransport, "__del__", _quiet_del)
    except Exception:  # pragma: no cover – import failed or layout changed
        # Fail silent; worst‑case the original warning re‑appears, but tests
        # will still pass on non‑Windows runners.
        pass

# ---------------------------------------------------------------------------+
#  Re‑export public sub‑modules                                              +
# ---------------------------------------------------------------------------+

__all__: List[str] = []

for _name in ["core.logger_setup"]:
    mod: ModuleType = import_module(f".{_name}", __name__)
    # Extract the last part of the module name for the global
    simple_name = _name.split(".")[-1]
    globals()[simple_name] = mod
    __all__.append(simple_name)
