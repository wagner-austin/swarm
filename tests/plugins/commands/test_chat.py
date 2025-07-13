from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.core.containers import Container


@pytest.fixture
def container_with_mocked_history() -> tuple[Container, MagicMock, MagicMock]:
    """Create real DI container with mocked history backend."""
    container = Container()

    # Mock history backend
    mock_history = MagicMock(spec=["clear", "record", "recent"])
    mock_history.clear = AsyncMock()
    mock_history.record = AsyncMock()
    mock_history.recent = AsyncMock(return_value=[])
    container.history_backend.override(mock_history)

    # Mock bot
    mock_bot = MagicMock()
    mock_bot.user = MagicMock()
    mock_bot.user.id = 123
    mock_bot.user.name = "TestBot"
    mock_bot.owner_id = 123
    mock_bot.is_ready.return_value = True
    mock_bot.is_closed.return_value = False
    mock_bot.container = container

    return container, mock_bot, mock_history


@pytest.mark.asyncio
@patch("bot.plugins.commands.chat.safe_send")
async def test_chat_clear_history(
    mock_safe_send: AsyncMock,
    container_with_mocked_history: tuple[Container, MagicMock, MagicMock],
) -> None:
    """Test chat clear history using real DI container."""
    container, mock_bot, mock_history = container_with_mocked_history

    # Create Chat cog using REAL DI container factory
    chat_cog = container.chat_cog(bot=mock_bot)

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
    mock_history.clear.assert_awaited_once()


@pytest.mark.asyncio
@patch("bot.plugins.commands.chat.safe_send")
@patch("bot.plugins.commands.chat._providers.get")
@patch("bot.plugins.commands.chat.settings", autospec=True)
async def test_chat_simple_reply(
    mock_settings: MagicMock,
    mock_get: MagicMock,
    mock_safe_send: AsyncMock,
    container_with_mocked_history: tuple[Container, MagicMock, MagicMock],
) -> None:
    """Test chat simple reply using real DI container."""
    container, mock_bot, mock_history = container_with_mocked_history

    # Create Chat cog using REAL DI container factory
    chat_cog = container.chat_cog(bot=mock_bot)
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
