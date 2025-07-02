from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.frontends.discord.discord_owner import clear_owner_cache
from bot.plugins.commands.alert_pump import AlertPump


@pytest.fixture
def mock_bot() -> MagicMock:
    bot = MagicMock()
    bot.owner_id = 123
    bot.get_user.return_value = MagicMock(id=123)
    bot.is_ready.return_value = True
    bot.is_closed.return_value = False
    bot.lifecycle = MagicMock()
    bot.lifecycle.alerts_q = MagicMock()

    # Mock the async methods that get_owner depends on
    from discord import Object

    bot.fetch_user = AsyncMock()
    bot.fetch_user.return_value = Object(id=123)

    bot.application_info = AsyncMock()
    bot.application_info.return_value.owner = Object(id=123)

    return bot


@pytest.fixture
def alert_pump_cog(mock_bot: MagicMock) -> AlertPump:
    return AlertPump(bot=mock_bot)


@pytest.mark.asyncio
async def test_cog_load_and_unload(alert_pump_cog: AlertPump) -> None:
    """Verify that cog_load starts the background task and cog_unload cancels it."""
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
async def test_on_ready_sends_startup_dm(alert_pump_cog: AlertPump) -> None:
    """Verify the on_ready listener sends the startup DM once."""
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
async def test_send_dm_with_retry_success(alert_pump_cog: AlertPump) -> None:
    owner = MagicMock()
    owner.send = AsyncMock()
    await alert_pump_cog._send_dm_with_retry(owner, content="Test alert!")
    owner.send.assert_awaited_once_with("Test alert!")


@pytest.mark.asyncio
async def test_send_dm_with_retry_embed(alert_pump_cog: AlertPump) -> None:
    owner = MagicMock()
    owner.send = AsyncMock()
    embed = MagicMock()
    await alert_pump_cog._send_dm_with_retry(owner, content=None, embed=embed)
    owner.send.assert_awaited_once_with(content=None, embed=embed)
