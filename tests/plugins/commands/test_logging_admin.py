from __future__ import annotations

import logging
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from discord import Object

from bot.plugins.commands.logging_admin import LoggingAdmin


@pytest.fixture
def mock_bot() -> MagicMock:
    """Fixture for a mock bot instance."""
    bot = MagicMock()
    bot.owner_id = 12345
    bot.application_info = AsyncMock()
    bot.application_info.return_value.owner = Object(id=12345)
    return bot


@pytest.fixture
def logging_admin_cog(mock_bot: MagicMock) -> LoggingAdmin:
    """Fixture for the LoggingAdmin cog instance."""
    return LoggingAdmin(bot=mock_bot)


@pytest.mark.asyncio
@patch("bot.plugins.commands.logging_admin.safe_send")
async def test_loglevel_get_as_owner(
    mock_safe_send: AsyncMock,
    logging_admin_cog: LoggingAdmin,
    mock_bot: MagicMock,
) -> None:
    """Test that the owner can get the current log level."""
    # Arrange
    mock_interaction = MagicMock()
    mock_interaction.user.id = mock_bot.owner_id
    root_logger = logging.getLogger()
    original_level = root_logger.level
    root_logger.setLevel(logging.INFO)

    # Act
    await cast(Any, logging_admin_cog.loglevel.callback)(
        logging_admin_cog, mock_interaction, level=None
    )

    # Assert
    mock_safe_send.assert_called_once()
    call_args, call_kwargs = mock_safe_send.call_args
    embed = call_kwargs.get("embed")
    assert embed is not None
    assert "Current log level" in embed.title
    assert "INFO" in embed.description
    assert call_kwargs.get("ephemeral") is True

    # Cleanup
    root_logger.setLevel(original_level)


@pytest.mark.asyncio
@patch("bot.plugins.commands.logging_admin.safe_send")
async def test_loglevel_set_valid_as_owner(
    mock_safe_send: AsyncMock,
    logging_admin_cog: LoggingAdmin,
    mock_bot: MagicMock,
) -> None:
    """Test that the owner can set a valid log level."""
    # Arrange
    mock_interaction = MagicMock()
    mock_interaction.user.id = mock_bot.owner_id
    root_logger = logging.getLogger()
    original_level = root_logger.level
    root_logger.setLevel(logging.INFO)

    # Act
    await cast(Any, logging_admin_cog.loglevel.callback)(
        logging_admin_cog, mock_interaction, level="DEBUG"
    )

    # Assert
    assert root_logger.level == logging.DEBUG
    mock_safe_send.assert_called_once()
    call_args, call_kwargs = mock_safe_send.call_args
    embed = call_kwargs.get("embed")
    assert embed is not None
    assert "Log level updated" in embed.title
    assert "DEBUG" in embed.description

    # Cleanup
    root_logger.setLevel(original_level)


@pytest.mark.asyncio
@patch("bot.plugins.commands.logging_admin.safe_send")
async def test_loglevel_as_non_owner(
    mock_safe_send: AsyncMock, logging_admin_cog: LoggingAdmin
) -> None:
    """Test that a non-owner cannot use the loglevel command."""
    # Arrange
    mock_interaction = MagicMock()
    mock_interaction.user.id = 99999  # Not the owner

    # Act
    await cast(Any, logging_admin_cog.loglevel.callback)(
        logging_admin_cog, mock_interaction, level="DEBUG"
    )

    # Assert
    mock_safe_send.assert_called_once_with(
        mock_interaction, "❌ Only the bot owner can use this command.", ephemeral=True
    )
