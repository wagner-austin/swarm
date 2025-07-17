"""
Package bootstrap and startup patch importer.

This module applies startup-time patches to suppress benign warnings during
interpreter shutdown. It also re-exports key sub-modules to make them
accessible under the `swarm` namespace.
"""

from __future__ import annotations

from importlib import import_module
from types import ModuleType

# ---------------------------------------------------------------------------+
#  Apply shutdown-hygiene patches                                           +
# ---------------------------------------------------------------------------+
# Import once on startup to patch stdlib and third-party libraries.
# This module is safe to import on any platform and with any dependency set,
# as it internally handles platform-specific logic and optional dependencies.
try:
    import swarm.compat.shutdown_hygiene  # noqa: F401
except Exception:  # pragma: no cover
    # This should not happen, but as a safeguard, we don't want to crash.
    pass


# ---------------------------------------------------------------------------+
#  Re-export public sub-modules                                              +
# ---------------------------------------------------------------------------+

__all__: list[str] = []

for _name in ["core.logger_setup"]:
    mod: ModuleType = import_module(f".{_name}", __name__)
    # Extract the last part of the module name for the global
    simple_name = _name.split(".")[-1]
    globals()[simple_name] = mod
    __all__.append(simple_name)
