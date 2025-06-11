from __future__ import annotations
import pkgutil
from importlib import import_module
from types import ModuleType
from typing import Iterator

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
    prefix: str = f"{pkg}."

    for mod_info in sorted(
        pkgutil.walk_packages(root.__path__, prefix), key=lambda m: m.name
    ):
        if not mod_info.ispkg:
            yield mod_info.name
