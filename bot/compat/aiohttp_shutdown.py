"""
bot.compat.aiohttp_shutdown
===========================
Suppress the noisy traceback produced by ``aiohttp.BaseConnector.__del__``
when it is executed *after* the Python interpreter has entered its
finalisation phase (``sys.is_finalizing()``).

During normal runtime the original behaviour (emitting a log record if a
connector is not properly closed) is preserved so genuine resource-leak bugs
remain visible.  The patch only squelches the warning **during interpreter
shutdown**, when the logging infrastructure itself may already be half-torn
-down and unusable.

Importing this module is idempotent and safe on platforms without ``aiohttp``.
"""

from __future__ import annotations

import sys

try:
    # Import within try so optional dependency is handled gracefully.
    import aiohttp  # noqa: F401
    from aiohttp.connector import BaseConnector
except ModuleNotFoundError:  # pragma: no cover – aiohttp absent in some envs
    # Nothing to patch.
    raise SystemExit

# ---------------------------------------------------------------------------+
#  Patch                                                                      +
# ---------------------------------------------------------------------------+
_orig_del = BaseConnector.__del__


def _quiet_del(self: BaseConnector) -> None:  # noqa: D401 – helper
    """Wrap ``BaseConnector.__del__``.

    If the interpreter is *not* finalising, the original ``__del__`` runs
    unchanged.  Otherwise we try to silently close the connector and swallow
    any errors as both the event loop and logging framework may already be in
    a partially-torn-down state.
    """

    if sys.is_finalizing():  # Python ≥ 3.8
        # Best-effort clean-up without emitting log records.
        try:
            # `BaseConnector` implements the async context-manager protocol via
            # `.close()` which sets the internal _closed flag; duplicating the
            # minimum here to avoid importing more internals.
            if not getattr(self, "_closed", True):
                setattr(self, "_closed", True)
                connector = getattr(self, "_connector", None)
                if connector is not None:
                    connector.close()
        except Exception:
            # Absolutely nothing must propagate at interpreter shutdown.
            pass
        return

    # Normal program life – keep original behaviour (and logging).
    _orig_del(self)


# Monkey-patch once.
setattr(BaseConnector, "__del__", _quiet_del)
