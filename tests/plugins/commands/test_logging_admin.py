from __future__ import annotations

import logging
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from discord import Object

from swarm.core.containers import Container
from swarm.frontends.discord.discord_owner import clear_owner_cache


@pytest.fixture
def container_with_bot() -> tuple[Container, MagicMock]:
    """Create real DI container with mocked swarm."""
    container = Container()

    # Mock Discord bot
    discord_bot = MagicMock()
    discord_bot.owner_id = 12345
    discord_bot.container = container

    # Mock the async methods that get_owner depends on
    discord_bot.fetch_user = AsyncMock()
    discord_bot.fetch_user.return_value = Object(id=12345)

    discord_bot.application_info = AsyncMock()
    discord_bot.application_info.return_value.owner = Object(id=12345)

    return container, discord_bot


@pytest.mark.asyncio
@patch("swarm.plugins.commands.logging_admin.safe_send")
async def test_loglevel_get_as_owner(
    mock_safe_send: AsyncMock,
    container_with_bot: tuple[Container, MagicMock],
) -> None:
    """Test that the owner can get the current log level using real DI container."""
    container, mock_discord_bot = container_with_bot

    # Clear owner cache for test isolation
    clear_owner_cache()

    # Create LoggingAdmin cog using REAL DI container factory
    logging_admin_cog = container.logging_admin_cog(discord_bot=mock_discord_bot)

    # Arrange
    mock_interaction = MagicMock()
    mock_interaction.user.id = mock_discord_bot.owner_id
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
@patch("swarm.plugins.commands.logging_admin.safe_send")
async def test_loglevel_set_valid_as_owner(
    mock_safe_send: AsyncMock,
    container_with_bot: tuple[Container, MagicMock],
) -> None:
    """Test that the owner can set a valid log level using real DI container."""
    container, mock_discord_bot = container_with_bot

    # Clear owner cache for test isolation
    clear_owner_cache()

    # Create LoggingAdmin cog using REAL DI container factory
    logging_admin_cog = container.logging_admin_cog(discord_bot=mock_discord_bot)

    # Arrange
    mock_interaction = MagicMock()
    mock_interaction.user.id = mock_discord_bot.owner_id
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
@patch("swarm.plugins.commands.logging_admin.safe_send")
async def test_loglevel_as_non_owner(
    mock_safe_send: AsyncMock, container_with_bot: tuple[Container, MagicMock]
) -> None:
    """Test that a non-owner cannot use the loglevel command using real DI container."""
    container, mock_discord_bot = container_with_bot

    # Clear owner cache for test isolation
    clear_owner_cache()

    # Create LoggingAdmin cog using REAL DI container factory
    logging_admin_cog = container.logging_admin_cog(discord_bot=mock_discord_bot)

    # Arrange
    mock_interaction = MagicMock()
    mock_interaction.user.id = 99999  # Not the owner

    # Act
    await cast(Any, logging_admin_cog.loglevel.callback)(
        logging_admin_cog, mock_interaction, level="DEBUG"
    )

    # Assert
    mock_safe_send.assert_called_once_with(
        mock_interaction, "❌ Only the swarm owner can use this command.", ephemeral=True
    )
