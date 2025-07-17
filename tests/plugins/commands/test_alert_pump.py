from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from discord import Object

from swarm.core.containers import Container
from swarm.frontends.discord.discord_owner import clear_owner_cache


@pytest.fixture
def container_with_mocked_deps() -> tuple[Container, MagicMock, MagicMock]:
    """Create real DI container with mocked bot and lifecycle."""
    container = Container()

    # Mock lifecycle
    mock_lifecycle = MagicMock()
    mock_lifecycle.alerts_q = MagicMock()

    # Mock Discord bot
    discord_bot = MagicMock()
    discord_bot.owner_id = 123
    discord_bot.get_user.return_value = MagicMock(id=123)
    discord_bot.is_ready.return_value = True
    discord_bot.is_closed.return_value = False
    discord_bot.lifecycle = mock_lifecycle
    discord_bot.container = container

    # Mock the async methods that get_owner depends on
    discord_bot.fetch_user = AsyncMock()
    discord_bot.fetch_user.return_value = Object(id=123)

    discord_bot.application_info = AsyncMock()
    discord_bot.application_info.return_value.owner = Object(id=123)

    return container, discord_bot, mock_lifecycle


@pytest.mark.asyncio
async def test_cog_load_and_unload(
    container_with_mocked_deps: tuple[Container, MagicMock, MagicMock],
) -> None:
    """Verify that cog_load starts the background task and cog_unload cancels it using real DI container."""
    container, mock_bot, mock_lifecycle = container_with_mocked_deps

    # Create AlertPump cog using REAL DI container factory
    alert_pump_cog = container.alert_pump_cog(discord_bot=mock_bot, lifecycle=mock_lifecycle)

    # Pre-condition: task should not be running
    assert alert_pump_cog._task is None

    # Action: load the cog
    await alert_pump_cog.cog_load()

    # Post-condition: task should be created and running
    assert alert_pump_cog._task is not None
    assert not alert_pump_cog._task.done()

    # Action: unload the cog
    await alert_pump_cog.cog_unload()

    # Post-condition: task should be cancelled
    # Note: due to event loop timing, we check for cancelled() state.
    assert alert_pump_cog._task.cancelled()


@pytest.mark.asyncio
async def test_on_ready_sends_startup_dm(
    container_with_mocked_deps: tuple[Container, MagicMock, MagicMock],
) -> None:
    """Verify the on_ready listener sends the startup DM once using real DI container."""
    container, mock_bot, mock_lifecycle = container_with_mocked_deps

    # Create AlertPump cog using REAL DI container factory
    alert_pump_cog = container.alert_pump_cog(discord_bot=mock_bot, lifecycle=mock_lifecycle)

    clear_owner_cache()
    # Patch the helper used by the listener
    with patch.object(
        alert_pump_cog, "_send_dm_with_retry", new_callable=AsyncMock
    ) as mock_send_dm:
        # Pre-condition: DM has not been sent
        assert not alert_pump_cog._startup_alert_sent

        # Action: simulate the on_ready event
        await alert_pump_cog.on_ready()

        # Post-condition: startup DM was sent
        mock_send_dm.assert_called_once()
        assert alert_pump_cog._startup_alert_sent

        # Action: simulate a second on_ready event (e.g. reconnect)
        await alert_pump_cog.on_ready()

        # Post-condition: DM is not sent again
        mock_send_dm.assert_called_once()


@pytest.mark.asyncio
async def test_send_dm_with_retry_success(
    container_with_mocked_deps: tuple[Container, MagicMock, MagicMock],
) -> None:
    """Test send DM with retry success using real DI container."""
    container, mock_bot, mock_lifecycle = container_with_mocked_deps

    # Create AlertPump cog using REAL DI container factory
    alert_pump_cog = container.alert_pump_cog(discord_bot=mock_bot, lifecycle=mock_lifecycle)

    owner = MagicMock()
    owner.send = AsyncMock()
    await alert_pump_cog._send_dm_with_retry(owner, content="Test alert!")
    owner.send.assert_awaited_once_with("Test alert!")


@pytest.mark.asyncio
async def test_send_dm_with_retry_embed(
    container_with_mocked_deps: tuple[Container, MagicMock, MagicMock],
) -> None:
    """Test send DM with retry embed using real DI container."""
    container, mock_bot, mock_lifecycle = container_with_mocked_deps

    # Create AlertPump cog using REAL DI container factory
    alert_pump_cog = container.alert_pump_cog(discord_bot=mock_bot, lifecycle=mock_lifecycle)

    owner = MagicMock()
    owner.send = AsyncMock()
    embed = MagicMock()
    await alert_pump_cog._send_dm_with_retry(owner, content=None, embed=embed)
    owner.send.assert_awaited_once_with(content=None, embed=embed)
