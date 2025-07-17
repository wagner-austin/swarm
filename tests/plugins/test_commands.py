"""
Integration-level sanity check for *slash* cogs after prefix removal.
"""

from __future__ import annotations

import types
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from discord.ext import commands

from swarm.core.containers import Container
from swarm.plugins.commands.about import About
from swarm.plugins.commands.chat import Chat
from tests._mocks.mocks import StubInteraction

# ---------------------------------------------------------------------------+
# Tests                                                                      +
# ---------------------------------------------------------------------------+


@pytest.mark.asyncio
async def test_about_command() -> None:
    """/about should send an embed without raising."""
    discord_bot = AsyncMock(spec=commands.Bot)
    discord_bot.container = Container()
    cog = About(discord_bot)

    ix = StubInteraction(discord_bot=discord_bot)
    # mypy: 'callback' is dynamically bound; treat as Any
    await cast(Any, cog.about.callback)(cog, ix)

    # With safe_send, the helper may choose response.send_message or followup.send
    assert ix.response.send_message.await_count == 1 or ix.followup.send.await_count == 1


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
    discord_bot = AsyncMock(spec=commands.Bot)
    discord_bot.container = Container()
    discord_bot.is_owner = AsyncMock(return_value=True)

    cog = Chat(discord_bot)
    ix = StubInteraction(discord_bot=discord_bot)

    await cast(Any, cog.chat.callback)(cog, ix, "hi", sync_in_test=True)

    # we expect at least one follow-up send with "Hi!"
    sends: list[str] = [
        call.kwargs.get("content", "") or call.args[0] for call in ix.followup.send.await_args_list
    ]
    assert any("hi" in s.lower() for s in sends)
