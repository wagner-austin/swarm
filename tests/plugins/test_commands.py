"""
Integration-level sanity check for *slash* cogs after prefix removal.
"""

from __future__ import annotations

from typing import Any, List, cast
import types
import pytest
from unittest.mock import AsyncMock

import discord
from discord.ext import commands

from bot.plugins.commands.about import About
from bot.plugins.commands.chat import Chat

# ---------------------------------------------------------------------------+
# Minimal Interaction stub                                                   +
# ---------------------------------------------------------------------------+


class StubInteraction(AsyncMock):
    """Just enough of discord.Interaction for our slash handlers."""

    def __init__(self, *, bot: commands.Bot):
        super().__init__(spec=discord.Interaction)
        self.client = bot  # alias used by commands
        self.user = AsyncMock()  # needed for owner checks

        # response & followup each expose .send_message / .send
        self.response = AsyncMock()
        self.response.defer = AsyncMock()
        self.response.send_message = AsyncMock()

        self.followup = AsyncMock()
        self.followup.send = AsyncMock()


# ---------------------------------------------------------------------------+
# Tests                                                                      +
# ---------------------------------------------------------------------------+


@pytest.mark.asyncio
async def test_about_command() -> None:
    """/about should send an embed without raising."""
    bot = AsyncMock(spec=commands.Bot)
    cog = About(bot)

    ix = StubInteraction(bot=bot)
    # mypy: 'callback' is dynamically bound; treat as Any
    await cast(Any, cog.about.callback)(cog, ix)

    ix.response.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_chat_command(monkeypatch: Any) -> None:
    """Slash version of Chat responds with streamed text."""
    # ---- patch google.genai so no network happens -------------------------
    monkeypatch.setitem(
        __import__("sys").modules,
        "google",
        types.SimpleNamespace(
            genai=types.SimpleNamespace(
                Client=lambda api_key: types.SimpleNamespace(
                    models=types.SimpleNamespace(
                        generate_content_stream=lambda **kwargs: iter(
                            [types.SimpleNamespace(text="Hi!")]
                        )
                    )
                )
            )
        ),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "google.genai",
        types.SimpleNamespace(
            types=types.SimpleNamespace(
                Content=lambda **kwargs: None,
                Part=types.SimpleNamespace(from_text=lambda text: None),
                GenerateContentConfig=lambda **kwargs: None,
            )
        ),
    )

    # ----------------------------------------------------------------------
    bot = AsyncMock(spec=commands.Bot)
    bot.is_owner = AsyncMock(return_value=True)

    cog = Chat(bot)
    ix = StubInteraction(bot=bot)

    await cast(Any, cog.chat.callback)(cog, ix, "hi")

    # we expect at least one follow-up send with "Hi!"
    sends: List[str] = [
        call.kwargs.get("content", "") or call.args[0]
        for call in ix.followup.send.await_args_list
    ]
    assert any("hi" in s.lower() for s in sends)
