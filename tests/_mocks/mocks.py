"""
Mock objects used in tests.
These are intentionally separated from production code to avoid accidental imports.
"""

import types
from typing import Any
from unittest.mock import AsyncMock

import discord
from discord.ext.commands import Bot


class MockMessage:
    """A mock discord.Message object with an edit method."""

    def __init__(self, content: str | None = None, **kwargs: Any):
        self.content = content
        self.kwargs = kwargs  # Store original send kwargs
        self.edit_history: list[dict[str, Any]] = []  # To track edits, if needed for assertions

    async def edit(self, content: str | None = None, **kwargs: Any) -> "MockMessage":
        """Mock the edit method of a discord.Message."""
        edit_details = {}
        if content is not None:
            self.content = content
            edit_details["content"] = content

        # Update message's kwargs with edit's kwargs
        self.kwargs.update(kwargs)
        edit_details.update(kwargs)
        self.edit_history.append(edit_details)

        async def _noop() -> None:  # Keep the async nature
            pass

        await _noop()
        return self


class MockCtx:
    """
    A *very* small stand-in for `discord.ext.commands.Context`.
    The unit-tests use `.send()` (which returns a `MockMessage`) and `.sent` (list of initial contents).
    """

    sent: list[str]  # Using built-in list

    def __init__(self) -> None:
        self.sent = []

    async def send(
        self,
        content: str | None = None,
        **kwargs: Any,  # Capture other arguments like embeds, views, etc.
    ) -> "MockMessage":  # Return MockMessage
        if content is not None:
            self.sent.append(content)

        # a single awaited no-op keeps the signature async while
        # guaranteeing nothing is left un-awaited
        async def _noop() -> None:
            pass

        await _noop()

        return MockMessage(content=content, **kwargs)  # Return an instance of MockMessage


# ---------------------------------------------------------------------------+
# New helper: minimal slash Interaction stub                                 +
# ---------------------------------------------------------------------------+


class StubInteraction(AsyncMock):
    """
    A *very* small substitute for `discord.Interaction` used by unit tests.

    Implements:
      • .user         – dummy user (allows owner checks)
      • .response.defer()
      • .followup.send()
    """

    def __init__(self, *, discord_bot: Bot | None = None):
        super().__init__(spec=discord.Interaction)
        self.client = discord_bot
        # minimal user stub: discord.py slash checks only need `.id`
        self.user = types.SimpleNamespace(id=42, mention="@tester")

        # response / follow-up mocks
        self.response = AsyncMock()
        self.response.defer = AsyncMock()

        self.followup = AsyncMock()
        self.followup.send = AsyncMock()

        # Convenience for assertions
        self.sent_messages: list[str] = []
        # Also set sent_messages on followup for tests expecting it there
        self.followup.sent_messages = self.sent_messages

        # Capture content of follow-ups
        async def _capture(*_args: Any, **kw: Any) -> None:
            content = kw.get("content") or (_args[0] if _args else "")
            if isinstance(content, str):
                self.sent_messages.append(content)

        self.followup.send.side_effect = _capture
