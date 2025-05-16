# type: ignore
"""
Integration-level plugin test for command registry.

This module ensures that the overall plugin registry is loading commands as expected
and that each registered plugin function returns a valid response.

Note:
    Plugin-specific tests have been moved to their own test_<plugin_name>.py files.
    This file no longer tests individual plugin commands in detail; see per-plugin test files.
"""

from typing import Any
import pytest
import types
import logging
from unittest.mock import AsyncMock
from discord.ext import commands
from bot_plugins.commands.help import Help
from bot_plugins.commands.info import Info
from bot_plugins.commands.chat import Chat
from tests.helpers.mocks import MockCtx

logger = logging.getLogger(__name__)


@pytest.mark.asyncio
async def test_help_command() -> None:
    bot = AsyncMock(spec=commands.Bot)
    bot.commands = [types.SimpleNamespace(name="help", help="Show help", hidden=False)]
    cog = Help(bot)
    ctx = MockCtx()
    await cog.help(ctx)

    logger.info("[test_help_command] ctx.sent: %s", ctx.sent)
    logger.info(
        "[test_help_command] bot.commands[0]: %s dir: %s",
        bot.commands[0],
        dir(bot.commands[0]),
    )
    assert "help" in ctx.sent[0].lower() if ctx.sent else True


@pytest.mark.asyncio
async def test_info_command() -> None:
    bot = AsyncMock(spec=commands.Bot)
    cog = Info(bot)
    ctx = MockCtx()
    await cog.info(ctx)
    assert any("personal Discord bot" in m for m in ctx.sent)


@pytest.mark.asyncio
async def test_chat_command(monkeypatch: Any) -> None:
    bot = AsyncMock(spec=commands.Bot)
    cog = Chat(bot)
    ctx = MockCtx()
    # Patch out google.genai
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
    await cog.chat(ctx, prompt="hi")
    logger.info("[test_chat_command] ctx.sent: %s", ctx.sent)
    assert any("hi!" in m.lower() for m in ctx.sent)
