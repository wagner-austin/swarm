from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from discord import Object

from bot.core.containers import Container


@pytest.fixture
def container_with_bot() -> tuple[Container, MagicMock]:
    """Create real DI container with mocked bot."""
    container = Container()

    bot = MagicMock()
    bot.user = MagicMock()
    bot.user.id = 123
    bot.user.name = "TestBot"
    bot.user.avatar = None
    bot.container = container

    return container, bot


@pytest.mark.asyncio
@patch("bot.plugins.commands.about.safe_send")
@patch("bot.plugins.commands.about.get_bot_version", return_value="1.2.3")
async def test_about_command(
    mock_get_version: MagicMock,
    mock_safe_send: AsyncMock,
    container_with_bot: tuple[Container, MagicMock],
) -> None:
    """Test /about command using real DI container."""
    container, mock_bot = container_with_bot
    mock_interaction = AsyncMock()

    # Create About cog using REAL DI container factory
    about_cog = container.about_cog(
        bot=mock_bot,
    )

    await cast(Any, about_cog.about.callback)(about_cog, mock_interaction)

    mock_safe_send.assert_called_once()
    args, kwargs = mock_safe_send.call_args
    embed = kwargs["embed"]
    assert embed.title == f"{mock_bot.user.name} - About"
    assert "Version: 1.2.3" in embed.description
    assert "Austin Wagner" in embed.fields[0].value
    assert kwargs["ephemeral"] is True
