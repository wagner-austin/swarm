"""
bot.compat.win_asyncio
======================
Silence the benign transport/unclosed-session warning that appears on
CPython ≥ 3.11 under Windows when pytest (or the application) shuts down
while asyncio transports are still referenced.  The root cause is fixed
up-stream in CPython 3.14.  Until then we monkey-patch the same lines.

Importing this module is **idempotent** and has effect only on Windows.
It is safe to import unconditionally from any platform.
"""

from __future__ import annotations

import sys

# Abort early on non-Windows – perform zero work, keep import cheap.
if not sys.platform.startswith("win"):
    raise SystemExit

# ---------------------------------------------------------------------------+
#  Apply back-port patch to asyncio transports                                +
# ---------------------------------------------------------------------------+

from asyncio.base_subprocess import BaseSubprocessTransport  # noqa: SLF001 – internal import
from asyncio.proactor_events import _ProactorBasePipeTransport  # noqa: SLF001 – internal import


def _safe_repr(self: object) -> str:  # noqa: D401 – helper
    """Return a minimal repr that never touches closed sockets."""
    return f"<{self.__class__.__name__} fd=closed>"


# Replace the fragile __repr__ used by _ProactorBasePipeTransport.
setattr(_ProactorBasePipeTransport, "__repr__", _safe_repr)

# ---------------------------------------------------------------------------+
#  Subprocess transport finaliser – ignore benign RuntimeError               +
# ---------------------------------------------------------------------------+

_original_del = BaseSubprocessTransport.__del__


def _quiet_del(self: BaseSubprocessTransport) -> None:  # noqa: D401 – helper
    """Call original __del__, silencing the 'Event loop is closed' noise."""
    try:
        _original_del(self)
    except RuntimeError as exc:  # pragma: no cover – specific benign case only
        if str(exc) != "Event loop is closed":
            raise


setattr(BaseSubprocessTransport, "__del__", _quiet_del)
