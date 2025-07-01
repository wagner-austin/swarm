from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from bot.plugins.commands.status import Status


@pytest.fixture
def dummy_bot() -> MagicMock:
    bot = MagicMock(spec=discord.ext.commands.Bot)
    bot.container = MagicMock()
    bot.latency = 0.123
    bot.guilds = [MagicMock(), MagicMock()]
    bot.shard_id = 0
    bot.shard_count = 2
    return bot


@pytest.fixture
def interaction() -> MagicMock:
    inter = MagicMock(spec=discord.Interaction)
    inter.user.id = 12345
    inter.response.defer = AsyncMock()
    inter.followup.send = AsyncMock()
    return inter


@pytest.mark.asyncio
async def test_status_embed_fields(dummy_bot: MagicMock, interaction: MagicMock) -> None:
    mock_metrics = MagicMock()
    mock_metrics.get_stats.return_value = {
        "uptime_s": 7200,
        "discord_messages_processed": 42,
        "messages_sent": 24,
    }
    mock_metrics.format_hms.return_value = "2:00:00"
    mock_metrics.get_cpu_mem.return_value = ("5%", "256MB")
    mock_safe_send = AsyncMock()
    cog = Status(
        dummy_bot,
        metrics_mod=mock_metrics,
        safe_send_func=mock_safe_send,
    )
    await cast(Any, cog.status.callback)(cog, interaction)
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
async def test_status_shard_info(dummy_bot: MagicMock, interaction: MagicMock) -> None:
    mock_metrics = MagicMock()
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
    cog = Status(
        dummy_bot,
        metrics_mod=mock_metrics,
        safe_send_func=mock_safe_send,
    )
    await cast(Any, cog.status.callback)(cog, interaction)
    assert len(mock_safe_send.await_args_list) > 0, "safe_send was never called"
    embed = mock_safe_send.await_args_list[0].kwargs["embed"]
    # Shard info should be present and correct
    assert f"Shard {dummy_bot.shard_id + 1}/{dummy_bot.shard_count}" in embed.fields[-1].value


@pytest.mark.asyncio
async def test_status_no_shard(dummy_bot: MagicMock, interaction: MagicMock) -> None:
    mock_metrics = MagicMock()
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
    cog = Status(
        dummy_bot,
        metrics_mod=mock_metrics,
        safe_send_func=mock_safe_send,
    )
    await cast(Any, cog.status.callback)(cog, interaction)
    assert len(mock_safe_send.await_args_list) > 0, "safe_send was never called"
    embed = mock_safe_send.await_args_list[0].kwargs["embed"]
    # Shard info should be em dash
    assert "Shard —" in embed.fields[-1].value
