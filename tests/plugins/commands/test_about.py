from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from discord import Object

from bot.plugins.commands.about import About


@pytest.fixture
def mock_bot() -> MagicMock:
    bot = MagicMock()
    bot.user = MagicMock()
    bot.user.id = 123
    bot.user.name = "TestBot"
    bot.user.avatar = None
    return bot


@pytest.fixture
def about_cog(mock_bot: MagicMock) -> About:
    return About(bot=mock_bot)


@pytest.mark.asyncio
@patch("bot.plugins.commands.about.safe_send")
@patch("bot.plugins.commands.about.get_bot_version", return_value="1.2.3")
async def test_about_command(
    mock_get_version: MagicMock,
    mock_safe_send: AsyncMock,
    about_cog: About,
    mock_bot: MagicMock,
) -> None:
    mock_interaction = AsyncMock()
    await cast(Any, about_cog.about.callback)(about_cog, mock_interaction)
    mock_safe_send.assert_called_once()
    args, kwargs = mock_safe_send.call_args
    embed = kwargs["embed"]
    assert embed.title == f"{mock_bot.user.name} - About"
    assert "Version: 1.2.3" in embed.description
    assert "Austin Wagner" in embed.fields[0].value
    assert kwargs["ephemeral"] is True
