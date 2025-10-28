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
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from types import ModuleType
from typing import Protocol, TypeGuard, Unpack

from swarm.ai.contracts import GenerateOptions, LLMProvider, Message
from swarm.core.telemetry import record_llm_call

_log = logging.getLogger(__name__)

_REGISTRY: dict[str, LLMProvider] = {}

_pkg_path = Path(__file__).resolve().parent


class ModuleWithProvider(Protocol):
    provider: LLMProvider


def has_provider(mod: ModuleType) -> TypeGuard[ModuleWithProvider]:
    try:
        obj = getattr(mod, "provider")
    except Exception:
        return False
    return isinstance(obj, LLMProvider)


class _InstrumentedProvider(LLMProvider):
    def __init__(self, inner: LLMProvider) -> None:
        self._inner = inner
        self.name = inner.name

    async def generate(
        self,
        *,
        messages: list[Message],
        stream: bool = False,
        **kw: Unpack[GenerateOptions],
    ) -> str | AsyncIterator[str]:
        start = time.perf_counter()
        status = "ok"
        try:
            return await self._inner.generate(messages=messages, stream=stream, **kw)
        except Exception:
            status = "error"
            raise
        finally:
            record_llm_call(self.name, status, time.perf_counter() - start)


for _file in _pkg_path.iterdir():
    if _file.name.startswith("_") or _file.suffix != ".py" or _file.stem == "__init__":
        continue
    _mod: ModuleType = importlib.import_module(f"{__name__}.{_file.stem}")
    if has_provider(_mod):
        prov = _mod.provider
        _REGISTRY[prov.name] = _InstrumentedProvider(prov)
        _log.debug("LLM provider '%s' wrapped with telemetry", prov.name)


def get(name: str) -> LLMProvider:
    """Return the provider instance registered under *name*."""

    return _REGISTRY[name]


def all() -> dict[str, LLMProvider]:
    """Return a shallow copy of the current registry mapping."""

    return dict(_REGISTRY)


__all__ = ["get", "all"]
