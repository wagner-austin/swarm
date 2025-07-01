from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.plugins.commands.chat import Chat


@pytest.fixture
def mock_bot() -> MagicMock:
    bot = MagicMock()
    bot.user = MagicMock()
    bot.user.id = 123
    bot.user.name = "TestBot"
    bot.owner_id = 123
    bot.is_ready.return_value = True
    bot.is_closed.return_value = False
    return bot


@pytest.fixture
def mock_history_backend() -> MagicMock:
    backend = MagicMock(spec=["clear", "record", "recent"])
    backend.clear = AsyncMock()
    backend.record = AsyncMock()
    backend.recent = AsyncMock(return_value=[])
    return backend


@pytest.fixture
def chat_cog(mock_bot: MagicMock, mock_history_backend: MagicMock) -> Chat:
    return Chat(bot=mock_bot, history_backend=mock_history_backend)


@pytest.mark.asyncio
@patch("bot.plugins.commands.chat.safe_send")
async def test_chat_clear_history(
    mock_safe_send: AsyncMock, chat_cog: Chat, mock_bot: MagicMock
) -> None:
    mock_interaction: MagicMock = MagicMock()
    mock_interaction.channel_id = 1
    mock_interaction.user.id = 123
    mock_interaction.response = MagicMock()
    mock_interaction.response.defer = AsyncMock()
    mock_interaction.followup = MagicMock(send=AsyncMock())
    await cast(Any, chat_cog.chat.callback)(
        chat_cog, mock_interaction, prompt=None, clear=True, personality=None
    )
    mock_safe_send.assert_called()
    cast(MagicMock, chat_cog._history.clear).assert_awaited_once()


@pytest.mark.asyncio
@patch("bot.plugins.commands.chat.safe_send")
@patch("bot.plugins.commands.chat._providers.get")
@patch("bot.plugins.commands.chat.settings", autospec=True)
async def test_chat_simple_reply(
    mock_settings: MagicMock,
    mock_get: MagicMock,
    mock_safe_send: AsyncMock,
    chat_cog: Chat,
    mock_bot: MagicMock,
) -> None:
    mock_interaction: MagicMock = MagicMock()
    mock_interaction.channel_id = 1
    mock_interaction.user.id = 123
    mock_interaction.response = MagicMock()
    mock_interaction.response.defer = AsyncMock()
    mock_interaction.followup = MagicMock(send=AsyncMock())
    # Ensure defer is awaitable
    mock_interaction.response = MagicMock()
    mock_interaction.response.defer = AsyncMock()
    mock_interaction.followup = MagicMock(send=AsyncMock())
    mock_settings.llm_provider = "mock"
    mock_provider = MagicMock()
    mock_provider.generate = AsyncMock(return_value="Hello!")
    mock_get.return_value = mock_provider
    await cast(Any, chat_cog.chat.callback)(
        chat_cog, mock_interaction, prompt="Hello", clear=False, personality=None
    )
    mock_safe_send.assert_called()
    cast(MagicMock, chat_cog._history.record).assert_awaited_once()
