"""Dynamic LLM provider registry.

Concrete adapters (e.g. ``gemini.py``) must expose a *configured* singleton
called ``provider`` that satisfies :class:`bot.ai.contracts.LLMProvider` and
sets a unique ``name`` attribute.  At import-time this package walks its own
sub-modules, collects any such singletons, and makes them available via
:func:`get` / :func:`all`.

The dynamic discovery keeps vendor SDKs isolated inside their adapter modules
and lets tests *override* the registry with stubs effortlessly::

    from bot.ai import providers

    providers._registry.clear()
    providers._registry["dummy"] = DummyProvider()

This avoids monkey-patching import paths.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from types import ModuleType
from typing import Dict, cast

from bot.ai.contracts import LLMProvider

_REGISTRY: Dict[str, LLMProvider] = {}

_pkg_path = Path(__file__).resolve().parent

for _file in _pkg_path.iterdir():
    if _file.name.startswith("_") or _file.suffix != ".py" or _file.stem == "__init__":
        continue
    _mod: ModuleType = importlib.import_module(f"{__name__}.{_file.stem}")
    if hasattr(_mod, "provider"):
        prov = cast(LLMProvider, getattr(_mod, "provider"))
        _REGISTRY[prov.name] = prov


def get(name: str) -> LLMProvider:
    """Return the provider instance registered under *name*."""

    return _REGISTRY[name]


def all() -> Dict[str, LLMProvider]:
    """Return a shallow copy of the current registry mapping."""

    return dict(_REGISTRY)


__all__ = ["get", "all"]
