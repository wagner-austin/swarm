from __future__ import annotations

from collections.abc import Iterator
from importlib import import_module, resources
from pathlib import PurePath
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
    root_files = resources.files(root)

    module_names = [
        f"{pkg}." + ".".join(PurePath(path.relative_to(root_files)).with_suffix("").parts)
        for path in root_files.rglob("*.py")  # type: ignore[attr-defined]
        if path.name != "__init__.py"
    ]

    # Ruff UP028: use `yield from` for simplicity
    yield from sorted(module_names)
