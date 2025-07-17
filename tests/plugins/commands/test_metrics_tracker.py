import asyncio
from unittest.mock import MagicMock

import discord
import pytest
from discord.ext import commands

from swarm.core.containers import Container


@pytest.fixture
def container_with_mocked_metrics() -> tuple[Container, MagicMock, MagicMock]:
    """Create real DI container with mocked metrics."""
    container = Container()

    # Mock metrics
    mock_metrics = MagicMock()
    container.metrics_helper.override(mock_metrics)

    # Mock Discord bot
    mock_discord_bot = MagicMock(spec=commands.Bot)
    mock_discord_bot.user = MagicMock(id=1234)
    mock_discord_bot.latency = 0.123
    mock_discord_bot.container = container

    return container, mock_discord_bot, mock_metrics


@pytest.mark.asyncio
async def test_metrics_tracker_increments_metrics(
    container_with_mocked_metrics: tuple[Container, MagicMock, MagicMock],
) -> None:
    """Test metrics tracker increments metrics using real DI container."""
    container, mock_discord_bot, mock_metrics = container_with_mocked_metrics

    # Create MetricsTracker cog using REAL DI container factory
    cog = container.metrics_tracker_cog(discord_bot=mock_discord_bot)

    # Simulate on_message from self
    message = MagicMock()
    message.author.id = mock_discord_bot.user.id
    await cog.on_message(message)
    mock_metrics.increment_message_count.assert_called_once()
    mock_metrics.increment_discord_message_count.assert_not_called()

    mock_metrics.reset_mock()
    # Simulate on_message from another user
    message.author.id = 9999
    await cog.on_message(message)
    mock_metrics.increment_discord_message_count.assert_called_once()
    mock_metrics.increment_message_count.assert_not_called()

    # Simulate on_interaction from another user
    interaction = MagicMock()
    interaction.type.name = "application_command"
    interaction.user.id = 9999
    await cog.on_interaction(interaction)
    mock_metrics.increment_discord_message_count.assert_called()

    # Simulate on_interaction from self (should not increment)
    mock_metrics.reset_mock()
    interaction.user.id = mock_discord_bot.user.id
    await cog.on_interaction(interaction)
    mock_metrics.increment_discord_message_count.assert_not_called()
