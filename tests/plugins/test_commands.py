"""
File: tests/plugins/test_commands.py - Integration-level plugin test.
Ensures that the overall plugin registry is loading commands as expected
and that each registered plugin function returns a valid response.

Note: Plugin-specific tests have been moved to their own test_<plugin_name>.py files.
This file no longer tests individual plugin commands in detail; see per-plugin test files.
"""

import pytest
import types
from unittest.mock import AsyncMock
from discord.ext import commands
from bot_plugins.commands.help import Help
from bot_plugins.commands.info import Info
from bot_plugins.commands.chat import Chat

class DummyCtx:
    def __init__(self):
        self.sent = []
    async def send(self, msg):
        self.sent.append(msg)

@pytest.mark.asyncio
async def test_help_command():
    bot = AsyncMock(spec=commands.Bot)
    bot.commands = [types.SimpleNamespace(name="help", help="Show help", hidden=False)]
    cog = Help(bot)
    ctx = DummyCtx()
    await cog.help(ctx)
    assert any("help" in m for m in ctx.sent)

@pytest.mark.asyncio
async def test_info_command():
    bot = AsyncMock(spec=commands.Bot)
    cog = Info(bot)
    ctx = DummyCtx()
    await cog.info(ctx)
    assert any("volunteer-coordination" in m for m in ctx.sent)

@pytest.mark.asyncio
async def test_chat_command(monkeypatch):
    bot = AsyncMock(spec=commands.Bot)
    cog = Chat(bot)
    ctx = DummyCtx()
    # Patch out google.genai
    monkeypatch.setitem(__import__("sys").modules, "google", types.SimpleNamespace(genai=types.SimpleNamespace(Client=lambda api_key: types.SimpleNamespace(models=types.SimpleNamespace(generate_content_stream=lambda **kwargs: iter([types.SimpleNamespace(text="Hi!")]))))))
    monkeypatch.setitem(__import__("sys").modules, "google.genai", types.SimpleNamespace(types=types.SimpleNamespace(Content=lambda **kwargs: None, Part=types.SimpleNamespace(from_text=lambda text: None), GenerateContentConfig=lambda **kwargs: None)))
    await cog.chat(ctx, prompt="hi")
    assert any("Hi!" in m for m in ctx.sent)

# End of tests/plugins/test_commands.py