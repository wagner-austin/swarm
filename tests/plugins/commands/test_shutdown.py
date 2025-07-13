from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from pytest_mock import MockerFixture

from bot.core.containers import Container


@pytest.fixture
def container_with_mocked_shutdown() -> tuple[
    Container, MagicMock, MagicMock, MagicMock, AsyncMock
]:
    """Create real DI container with mocked shutdown dependencies."""
    container = Container()

    # Mock metrics
    mock_metrics = MagicMock()
    container.metrics_helper.override(mock_metrics)

    # Mock lifecycle (lifecycle is providers.Dependency, so we don't override it)
    mock_lifecycle = MagicMock()
    mock_lifecycle.shutdown = AsyncMock()

    # Mock get_owner function
    mock_get_owner = AsyncMock(return_value=MagicMock(id=12345))

    # Mock bot
    mock_bot = MagicMock(spec=discord.ext.commands.Bot)
    mock_bot.container = container

    return container, mock_bot, mock_metrics, mock_lifecycle, mock_get_owner


@pytest.fixture
def interaction() -> MagicMock:
    inter = MagicMock(spec=discord.Interaction)
    inter.user.id = 12345
    inter.client = MagicMock()
    inter.client.close = AsyncMock()
    return inter


@pytest.mark.asyncio
async def test_shutdown_owner_success(
    interaction: MagicMock,
    container_with_mocked_shutdown: tuple[Container, MagicMock, MagicMock, MagicMock, AsyncMock],
) -> None:
    """Test shutdown command success using real DI container."""
    container, mock_bot, mock_metrics, mock_lifecycle, mock_get_owner = (
        container_with_mocked_shutdown
    )

    mock_metrics.get_stats.return_value = {
        "uptime_s": 3600,
        "discord_messages_processed": 10,
        "messages_sent": 20,
    }
    mock_metrics.format_hms.return_value = "1:00:00"
    mock_safe_send = AsyncMock()

    # Create Shutdown cog using REAL DI container factory
    cog = container.shutdown_cog(
        bot=mock_bot,
        lifecycle=mock_lifecycle,
        get_owner_func=mock_get_owner,
        safe_send_func=mock_safe_send,
    )

    await cog._shutdown_impl(interaction)
    mock_safe_send.assert_any_call(interaction, "📴 Shutting down…")
    # Should send embed with stats
    assert mock_safe_send.call_args_list[-1][1]["embed"].title == "Shutdown complete"
    # Lifecycle shutdown should be called
    mock_lifecycle.shutdown.assert_awaited_once_with(signal_name="command")
    # Bot close should NOT be called directly
    assert interaction.client.close.await_count == 0


@pytest.mark.asyncio
async def test_shutdown_not_owner(
    interaction: MagicMock,
    container_with_mocked_shutdown: tuple[Container, MagicMock, MagicMock, MagicMock, AsyncMock],
) -> None:
    """Test shutdown command rejection for non-owner using real DI container."""
    container, mock_bot, mock_metrics, mock_lifecycle, _ = container_with_mocked_shutdown

    mock_get_owner = AsyncMock(return_value=MagicMock(id=99999))
    mock_safe_send = AsyncMock()

    # Create Shutdown cog using REAL DI container factory
    cog = container.shutdown_cog(
        bot=mock_bot,
        lifecycle=mock_lifecycle,
        get_owner_func=mock_get_owner,
        safe_send_func=mock_safe_send,
    )

    await cog._shutdown_impl(interaction)
    mock_safe_send.assert_awaited_with(interaction, "❌ Owner only.", ephemeral=True)
    # Lifecycle shutdown should not be called
    mock_lifecycle.shutdown.assert_not_awaited()
    # Bot close should not be called
    assert not interaction.client.close.await_count


@pytest.mark.asyncio
async def test_shutdown_owner_lookup_failure(
    interaction: MagicMock,
    container_with_mocked_shutdown: tuple[Container, MagicMock, MagicMock, MagicMock, AsyncMock],
) -> None:
    """Test shutdown command owner lookup failure using real DI container."""
    container, mock_bot, mock_metrics, mock_lifecycle, _ = container_with_mocked_shutdown

    mock_get_owner = AsyncMock(side_effect=RuntimeError)
    mock_safe_send = AsyncMock()

    # Create Shutdown cog using REAL DI container factory
    cog = container.shutdown_cog(
        bot=mock_bot,
        lifecycle=mock_lifecycle,
        get_owner_func=mock_get_owner,
        safe_send_func=mock_safe_send,
    )

    await cog._shutdown_impl(interaction)
    mock_safe_send.assert_awaited_with(
        interaction, "❌ Could not resolve bot owner.", ephemeral=True
    )
    mock_lifecycle.shutdown.assert_not_awaited()
    assert not interaction.client.close.await_count
