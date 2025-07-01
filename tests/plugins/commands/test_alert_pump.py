from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
    return bot


@pytest.fixture
def alert_pump_cog(mock_bot: MagicMock) -> AlertPump:
    return AlertPump(bot=mock_bot)


@pytest.mark.asyncio
async def test_cog_load_and_unload(alert_pump_cog: AlertPump, mock_bot: MagicMock) -> None:
    # Test that cog_load sets up the relay task and sends the startup embed
    with patch.object(
        alert_pump_cog, "_send_dm_with_retry", new_callable=AsyncMock
    ) as mock_send_dm:
        await alert_pump_cog.cog_load()
        mock_send_dm.assert_called()  # Should send the startup DM or queue it
        assert alert_pump_cog._task is not None
        # Now test unload cancels the task
        await alert_pump_cog.cog_unload()
        assert alert_pump_cog._task.done() or alert_pump_cog._task.cancelled()


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
