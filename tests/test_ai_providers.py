"""Tests for the dynamic LLM provider registry (PR-1).

These tests guarantee that the public contract introduced in `bot.ai.*` keeps
working as other parts of the code-base evolve.
"""

from __future__ import annotations

import sys
import types
from collections.abc import AsyncIterator, Iterator
from typing import Any, cast

import pytest

from bot.ai import providers as registry
from bot.ai.contracts import LLMProvider


@pytest.fixture(autouse=True)
def _isolate_registry() -> Iterator[None]:
    """Snapshot & restore the global registry so tests remain hermetic."""

    snapshot = registry.all()
    yield
    registry._REGISTRY.clear()
    registry._REGISTRY.update(snapshot)


@pytest.mark.asyncio
async def test_stub_provider_runtime_check_and_helpers() -> None:
    """Register a stub provider on-the-fly and validate helper functions."""

    # Build a fake provider module dynamically so it resembles real adapters
    mod = types.ModuleType("bot.ai.providers._stub")

    class StubProvider:
        """Minimal stub implementing the LLMProvider contract."""  # noqa: D101  (docstring not needed in test code)

        name = "stub"

        async def generate(
            self,
            *,
            messages: list[dict[str, str]],
            stream: bool = False,
            **opts: Any,
        ) -> str | AsyncIterator[str]:
            if stream:

                async def _aiter() -> AsyncIterator[str]:  # noqa: D401 – helper
                    yield "hi"

                return _aiter()
            return "hi"

    # Expose the singleton exactly like real provider modules do
    mod.provider = StubProvider()  # type: ignore[attr-defined]
    sys.modules[mod.__name__] = mod

    # Manually register – simulates what bot.ai.providers.__init__ auto-import does
    registry._REGISTRY["stub"] = cast(LLMProvider, mod.provider)

    # 1. Structural runtime check
    assert isinstance(mod.provider, LLMProvider)

    # 2. Helper functions work
    assert registry.get("stub") is mod.provider
    assert "stub" in registry.all()

    # 3. Functional path: streaming iterator
    stream_obj = await registry.get("stub").generate(messages=[], stream=True)
    assert hasattr(stream_obj, "__anext__")  # narrow type for mypy
    first_chunk = await cast(AsyncIterator[str], stream_obj).__anext__()
    assert first_chunk == "hi"
