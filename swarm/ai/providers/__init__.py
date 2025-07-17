"""Dynamic LLM provider registry.

Concrete adapters (e.g. ``gemini.py``) must expose a *configured* singleton
called ``provider`` that satisfies :class:`swarm.ai.contracts.LLMProvider` and
sets a unique ``name`` attribute.  At import-time this package walks its own
sub-modules, collects any such singletons, and makes them available via
:func:`get` / :func:`all`.

The dynamic discovery keeps vendor SDKs isolated inside their adapter modules
and lets tests *override* the registry with stubs effortlessly::

    from swarm.ai import providers

    providers._registry.clear()
    providers._registry["dummy"] = DummyProvider()

This avoids monkey-patching import paths.
"""

from __future__ import annotations

import functools
import importlib
import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, cast

from swarm.ai.contracts import LLMProvider
from swarm.core.telemetry import record_llm_call

_log = logging.getLogger(__name__)

_REGISTRY: dict[str, LLMProvider] = {}

_pkg_path = Path(__file__).resolve().parent

for _file in _pkg_path.iterdir():
    if _file.name.startswith("_") or _file.suffix != ".py" or _file.stem == "__init__":
        continue
    _mod: ModuleType = importlib.import_module(f"{__name__}.{_file.stem}")
    if hasattr(_mod, "provider"):
        prov = cast(LLMProvider, getattr(_mod, "provider"))
        _REGISTRY[prov.name] = prov

        # ------------------------------------------------------------+
        #  ✨  Middleware – wrap .generate for metrics + trace logs    |
        # ------------------------------------------------------------+

        async def _timed_generate(
            *args: Any,
            _call: Callable[..., Awaitable[Any]] = prov.generate,
            _provider_name: str = prov.name,
            **kw: Any,
        ) -> Any:
            start = time.perf_counter()
            status = "ok"
            try:
                result = await _call(*args, **kw)
                return result
            except Exception:
                status = "error"
                raise
            finally:
                record_llm_call(_provider_name, status, time.perf_counter() - start)

        # Only patch once
        if not hasattr(prov.generate, "__wrapped__"):
            _orig_generate: Callable[..., Awaitable[Any]] = prov.generate
            prov.generate = functools.wraps(_orig_generate)(_timed_generate)  # type: ignore[method-assign]
            _log.debug("LLM provider '%s' wrapped with telemetry", prov.name)


def get(name: str) -> LLMProvider:
    """Return the provider instance registered under *name*."""

    return _REGISTRY[name]


def all() -> dict[str, LLMProvider]:
    """Return a shallow copy of the current registry mapping."""

    return dict(_REGISTRY)


__all__ = ["get", "all"]
