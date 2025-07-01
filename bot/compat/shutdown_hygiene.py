"""
bot.compat.shutdown_hygiene
===========================
Apply various monkey-patches to silence benign warnings that can appear
during interpreter shutdown.

These patches are consolidated here to be applied once at startup.
"""

from __future__ import annotations

import sys

# ---------------------------------------------------------------------------+
#  Patch 1: aiohttp.BaseConnector finaliser                                   +
# ---------------------------------------------------------------------------+
# Suppress the noisy traceback produced by ``aiohttp.BaseConnector.__del__``
# when it is executed *after* the Python interpreter has entered its
# finalisation phase (``sys.is_finalizing()``).
try:
    # Import within try so optional dependency is handled gracefully.
    from aiohttp.connector import BaseConnector

    _orig_aiohttp_del = BaseConnector.__del__

    def _quiet_aiohttp_del(self: BaseConnector) -> None:  # noqa: D401 – helper
        if sys.is_finalizing():
            try:
                if not getattr(self, "_closed", True):
                    setattr(self, "_closed", True)
                    connector = getattr(self, "_connector", None)
                    if connector is not None:
                        connector.close()
            except Exception:
                pass
            return
        _orig_aiohttp_del(self)

    setattr(BaseConnector, "__del__", _quiet_aiohttp_del)

except (ModuleNotFoundError, AttributeError):  # pragma: no cover
    # Nothing to patch if aiohttp is missing or its internals change.
    pass


# ---------------------------------------------------------------------------+
#  Patch 2: Windows asyncio transport finalisers                              +
# ---------------------------------------------------------------------------+
# Silence benign transport/unclosed-session warnings that appear on
# CPython >= 3.11 under Windows when the application shuts down.
if sys.platform.startswith("win"):
    try:
        from asyncio.base_subprocess import (  # noqa: SLF001
            BaseSubprocessTransport,
        )
        from asyncio.proactor_events import (  # noqa: SLF001
            _ProactorBasePipeTransport,
        )

        def _safe_repr(self: object) -> str:  # noqa: D401 – helper
            """Return a minimal repr that never touches closed sockets."""
            return f"<{self.__class__.__name__} fd=closed>"

        setattr(_ProactorBasePipeTransport, "__repr__", _safe_repr)

        _original_subprocess_del = BaseSubprocessTransport.__del__

        def _quiet_subprocess_del(self: BaseSubprocessTransport) -> None:  # noqa: D401
            """Call original __del__, silencing the 'Event loop is closed' noise."""
            try:
                _original_subprocess_del(self)
            except RuntimeError as exc:  # pragma: no cover
                if str(exc) != "Event loop is closed":
                    raise

        setattr(BaseSubprocessTransport, "__del__", _quiet_subprocess_del)

    except (ImportError, AttributeError):  # pragma: no cover
        # Nothing to patch if internals are missing or change.
        pass
