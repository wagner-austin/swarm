from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from pytest_mock import MockerFixture

from bot.plugins.commands.shutdown import Shutdown


@pytest.fixture
def dummy_bot() -> MagicMock:
    bot = MagicMock(spec=discord.ext.commands.Bot)
    bot.container = MagicMock()
    return bot


@pytest.fixture
def interaction() -> MagicMock:
    inter = MagicMock(spec=discord.Interaction)
    inter.user.id = 12345
    inter.client = MagicMock()
    inter.client.close = AsyncMock()
    return inter


@pytest.mark.asyncio
async def test_shutdown_owner_success(
    dummy_bot: MagicMock, interaction: MagicMock, mocker: MockerFixture
) -> None:
    mock_metrics = MagicMock()
    mock_metrics.get_stats.return_value = {
        "uptime_s": 3600,
        "discord_messages_processed": 10,
        "messages_sent": 20,
    }
    mock_metrics.format_hms.return_value = "1:00:00"
    mock_get_owner = AsyncMock(return_value=MagicMock(id=12345))
    mock_safe_send = AsyncMock()
    cog = Shutdown(
        dummy_bot,
        metrics_mod=mock_metrics,
        get_owner_func=mock_get_owner,
        safe_send_func=mock_safe_send,
    )
    await cog._shutdown_impl(interaction)
    mock_safe_send.assert_any_call(interaction, "📴 Shutting down…")
    # Should send embed with stats
    assert mock_safe_send.call_args_list[-1][1]["embed"].title == "Shutdown complete"
    # Bot close should be called
    assert interaction.client.close.await_count == 1


@pytest.mark.asyncio
async def test_shutdown_not_owner(
    dummy_bot: MagicMock, interaction: MagicMock, mocker: MockerFixture
) -> None:
    mock_get_owner = AsyncMock(return_value=MagicMock(id=99999))
    mock_safe_send = AsyncMock()
    cog = Shutdown(
        dummy_bot,
        get_owner_func=mock_get_owner,
        safe_send_func=mock_safe_send,
    )
    await cog._shutdown_impl(interaction)
    mock_safe_send.assert_awaited_with(interaction, "❌ Owner only.", ephemeral=True)
    # Bot close should not be called
    assert not interaction.client.close.await_count


@pytest.mark.asyncio
async def test_shutdown_owner_lookup_failure(
    dummy_bot: MagicMock, interaction: MagicMock, mocker: MockerFixture
) -> None:
    mock_get_owner = AsyncMock(side_effect=RuntimeError)
    mock_safe_send = AsyncMock()
    cog = Shutdown(
        dummy_bot,
        get_owner_func=mock_get_owner,
        safe_send_func=mock_safe_send,
    )
    await cog._shutdown_impl(interaction)
    mock_safe_send.assert_awaited_with(
        interaction, "❌ Could not resolve bot owner.", ephemeral=True
    )
    assert not interaction.client.close.await_count
