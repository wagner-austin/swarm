"""Smoke test for Chat cog with a dummy provider.

Validates that the dynamic provider registry and Chat integration work without
hitting any real LLM backend or Discord network.
"""

from __future__ import annotations

import types
from typing import Any, List, Generator, cast

import pytest

from bot.ai.contracts import LLMProvider, Message
from bot.ai import providers as registry
from bot.core.settings import settings
from bot.plugins.commands.chat import Chat


# ---------------------------------------------------------------------------
# fixtures & helpers
# ---------------------------------------------------------------------------


class DummyProvider(LLMProvider):
    """Minimal provider that echoes a fixed reply."""

    name = "dummy"

    async def generate(
        self, *, messages: List[Message], stream: bool = False, **opts: Any
    ) -> str:  # noqa: D401, FBT001, FBT002
        # Ensure the Chat cog actually forwarded the prompt as the last message
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"] == "hi"
        return "dummy reply"


class _Void:  # noqa: D401
    """No-op awaitable used for ``response.defer()``."""

    async def __call__(self, *args: object, **kwargs: object) -> None:  # noqa: D401
        return None


class _Resp:
    """Mimics :pyattr:`discord.Interaction.response` + ``followup``."""

    def __init__(self) -> None:
        self._done = False
        self._last: str | None = None
        self.followup = types.SimpleNamespace(send=self._send)

    # response helpers ------------------------------------------------------

    def is_done(self) -> bool:  # noqa: D401
        return self._done

    defer = _Void()

    async def send_message(self, *args: object, **kwargs: object) -> None:  # noqa: D401
        self._done = True

    # follow-up helper -------------------------------------------------------

    async def _send(self, content: str, *args: object, **kwargs: object) -> None:  # noqa: D401
        self._last = content

    # allow test to read what got sent
    @property
    def last(self) -> str | None:  # noqa: D401
        return self._last


class DummyInteraction:  # noqa: D401
    """Ultra-light imitation of :class:`discord.Interaction`."""

    def __init__(self) -> None:
        self.channel_id = 123
        self.channel = types.SimpleNamespace(id=123)
        self.user = types.SimpleNamespace(id=42)
        self.response = _Resp()
        self.followup = self.response.followup


# ---------------------------------------------------------------------------
# actual test
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _inject_dummy_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None, None, None]:  # noqa: D401
    """Swap registry + settings so `Chat` picks up :class:`DummyProvider`."""

    # 1) wipe registry and add stub
    registry._REGISTRY.clear()
    registry._REGISTRY["dummy"] = DummyProvider()

    # 2) force settings.llm_provider = "dummy"
    monkeypatch.setattr(settings, "llm_provider", "dummy", raising=False)
    yield


@pytest.mark.asyncio
async def test_chat_with_dummy_provider() -> None:  # noqa: D401
    # Minimal bot stub
    bot_stub = types.SimpleNamespace(user=None)

    cog = Chat(bot_stub)  # type: ignore[arg-type]  # instantiate cog with stub
    ixn = DummyInteraction()

    # Call the underlying callback to avoid Command wrappers
    from typing import Any  # local import to avoid top-level heavy deps

    await cast(Any, Chat.chat.callback)(cog, ixn, "hi", False, None)

    # Ensure the provider’s reply made it to Discord follow-up
    assert (ixn.response.last or "").find("dummy reply") != -1
