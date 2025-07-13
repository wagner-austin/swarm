from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from bot.core.containers import Container


@pytest.fixture
def container_with_mocked_metrics() -> tuple[Container, MagicMock]:
    """Create real DI container with mocked metrics."""
    container = Container()

    # Mock metrics helper
    mock_metrics = MagicMock()
    mock_metrics.get_stats.return_value = {
        "uptime_s": 7200,
        "discord_messages_processed": 42,
        "messages_sent": 24,
    }
    mock_metrics.format_hms.return_value = "2:00:00"
    mock_metrics.get_cpu_mem.return_value = ("5%", "256MB")
    container.metrics_helper.override(mock_metrics)

    return container, mock_metrics


@pytest.fixture
def dummy_bot(container_with_mocked_metrics: tuple[Container, MagicMock]) -> MagicMock:
    """Create a mocked bot with real DI container."""
    container, _ = container_with_mocked_metrics

    bot = MagicMock(spec=discord.ext.commands.Bot)
    bot.container = container
    bot.latency = 0.123
    bot.guilds = [MagicMock(), MagicMock()]
    bot.shard_id = 0
    bot.shard_count = 2
    return bot


@pytest.fixture
def interaction() -> MagicMock:
    """Create a properly mocked Discord interaction."""
    inter = MagicMock(spec=discord.Interaction)
    inter.user.id = 12345
    inter.response.defer = AsyncMock()
    inter.followup.send = AsyncMock()
    return inter


@pytest.mark.asyncio
async def test_status_embed_fields(
    dummy_bot: MagicMock,
    interaction: MagicMock,
    container_with_mocked_metrics: tuple[Container, MagicMock],
) -> None:
    """Test /status command using real DI container."""
    container, mock_metrics = container_with_mocked_metrics
    mock_safe_send = AsyncMock()

    # Create Status cog using REAL DI container factory
    cog = container.status_cog(
        bot=dummy_bot,
        safe_send_func=mock_safe_send,  # Override safe_send for testing
    )

    await cast(Any, cog.status.callback)(cog, interaction)

    # Verify metrics were called via real DI
    mock_metrics.get_stats.assert_called_once()
    mock_metrics.format_hms.assert_called_once_with(7200)
    mock_metrics.get_cpu_mem.assert_called_once()

    # Should send an embed with correct title and fields
    assert len(mock_safe_send.await_args_list) > 0, "safe_send was never called"
    assert mock_safe_send.await_args_list[0].kwargs["embed"].title == "Bot status"
    fields = mock_safe_send.await_args_list[0].kwargs["embed"].fields
    field_names = [f.name for f in fields]
    assert "Traffic" in field_names
    assert "Runtime" in field_names
    assert "Discord" in field_names
    # Should be ephemeral
    assert mock_safe_send.await_args_list[0].kwargs["ephemeral"] is True


@pytest.mark.asyncio
async def test_status_shard_info(
    dummy_bot: MagicMock,
    interaction: MagicMock,
    container_with_mocked_metrics: tuple[Container, MagicMock],
) -> None:
    """Test /status command with shard info using real DI container."""
    container, mock_metrics = container_with_mocked_metrics
    mock_metrics.get_stats.return_value = {
        "uptime_s": 3600,
        "discord_messages_processed": 10,
        "messages_sent": 20,
    }
    mock_metrics.format_hms.return_value = "1:00:00"
    mock_metrics.get_cpu_mem.return_value = ("10%", "512MB")
    mock_safe_send = AsyncMock()
    dummy_bot.shard_id = 1
    dummy_bot.shard_count = 3

    # Create Status cog using REAL DI container factory
    cog = container.status_cog(
        bot=dummy_bot,
        safe_send_func=mock_safe_send,
    )

    await cast(Any, cog.status.callback)(cog, interaction)
    assert len(mock_safe_send.await_args_list) > 0, "safe_send was never called"
    embed = mock_safe_send.await_args_list[0].kwargs["embed"]
    # Shard info should be present and correct
    assert f"Shard {dummy_bot.shard_id + 1}/{dummy_bot.shard_count}" in embed.fields[-1].value


@pytest.mark.asyncio
async def test_status_no_shard(
    dummy_bot: MagicMock,
    interaction: MagicMock,
    container_with_mocked_metrics: tuple[Container, MagicMock],
) -> None:
    """Test /status command without shard info using real DI container."""
    container, mock_metrics = container_with_mocked_metrics
    mock_metrics.get_stats.return_value = {
        "uptime_s": 100,
        "discord_messages_processed": 1,
        "messages_sent": 2,
    }
    mock_metrics.format_hms.return_value = "0:01:40"
    mock_metrics.get_cpu_mem.return_value = ("1%", "12MB")
    mock_safe_send = AsyncMock()
    dummy_bot.shard_id = None
    dummy_bot.shard_count = None

    # Create Status cog using REAL DI container factory
    cog = container.status_cog(
        bot=dummy_bot,
        safe_send_func=mock_safe_send,
    )
    await cast(Any, cog.status.callback)(cog, interaction)
    assert len(mock_safe_send.await_args_list) > 0, "safe_send was never called"
    embed = mock_safe_send.await_args_list[0].kwargs["embed"]
    # Shard info should be em dash
    assert "Shard —" in embed.fields[-1].value
