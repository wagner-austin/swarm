"""Tests for the /chat clear flag."""

from __future__ import annotations

from typing import Any, cast

import pytest
from unittest.mock import AsyncMock

from discord.ext import commands

from bot.core.containers import Container
from bot.plugins.commands.chat import Chat
from tests._mocks.mocks import StubInteraction


@pytest.mark.asyncio
async def test_chat_clear_flag() -> None:
    """Invoking /chat with `clear=True` should wipe conversation history."""
    # ------------------------------------------------------------------
    # Setup bot + cog
    # ------------------------------------------------------------------
    bot = AsyncMock(spec=commands.Bot)
    bot.container = Container()
    bot.is_owner = AsyncMock(return_value=True)

    cog = Chat(bot)

    # ------------------------------------------------------------------
    # Pre-populate history for channel 1234 / persona "default"
    # ------------------------------------------------------------------
    chan_id = 1234
    persona = "default"
    cog._history.record(chan_id, persona, "hello", "hi!")

    # Stub interaction with matching channel_id
    ix = StubInteraction(bot=bot)
    ix.channel_id = chan_id  # Attribute accessed by Chat command

    # ------------------------------------------------------------------
    # Call /chat clear
    # ------------------------------------------------------------------
    await cast(Any, cog.chat.callback)(cog, ix, None, True, None)

    # History for that channel should now be empty
    assert cog._history.get(chan_id, persona) == []

    # A confirmation message should have been sent
    ix.response.send_message.assert_awaited_once()
    args, kwargs = ix.response.send_message.await_args
    msg = kwargs.get("content") or (args[0] if args else "")
    assert "cleared" in msg.lower()
