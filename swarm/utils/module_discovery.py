from __future__ import annotations

import pkgutil
from collections.abc import Iterator
from importlib import import_module
from types import ModuleType

# Utility helpers for module/package discovery.
#
# Currently provides :func:`iter_submodules` which yields fully qualified module
# strings for every (non-package) sub-module located under a given *pkg*.

__all__ = ["iter_submodules"]


def iter_submodules(pkg: str) -> Iterator[str]:
    """Yield fully qualified names for every direct or nested sub-module in *pkg*.

    Only leaf modules (those where ``is_pkg is False``) are returned. The order
    of discovery is deterministic (depth-first, alphabetic within a level) so
    callers can rely on stable extension loading order across OSes.
    """

    root: ModuleType = import_module(pkg)

    # If the provided name is not a package (e.g., a single module), nothing to do.
    if not hasattr(root, "__path__"):
        return

    module_names = [
        name
        for _, name, is_pkg in pkgutil.walk_packages(root.__path__, prefix=f"{pkg}.")
        if not is_pkg
    ]

    # Deterministic ordering across platforms.
    yield from sorted(module_names)
