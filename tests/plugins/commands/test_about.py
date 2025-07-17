from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from discord import Object

from swarm.core.containers import Container


@pytest.fixture
def container_with_bot() -> tuple[Container, MagicMock]:
    """Create real DI container with mocked swarm."""
    container = Container()

    discord_bot = MagicMock()
    discord_bot.user = MagicMock()
    discord_bot.user.id = 123
    discord_bot.user.name = "TestBot"
    discord_bot.user.avatar = None
    discord_bot.container = container

    return container, discord_bot


@pytest.mark.asyncio
@patch("swarm.plugins.commands.about.safe_send")
@patch("swarm.plugins.commands.about.get_bot_version", return_value="1.2.3")
async def test_about_command(
    mock_get_version: MagicMock,
    mock_safe_send: AsyncMock,
    container_with_bot: tuple[Container, MagicMock],
) -> None:
    """Test /about command using real DI container."""
    container, mock_discord_bot = container_with_bot
    mock_interaction = AsyncMock()

    # Create About cog using REAL DI container factory
    about_cog = container.about_cog(
        discord_bot=mock_discord_bot,
    )

    await cast(Any, about_cog.about.callback)(about_cog, mock_interaction)

    mock_safe_send.assert_called_once()
    args, kwargs = mock_safe_send.call_args
    embed = kwargs["embed"]
    assert embed.title == f"{mock_discord_bot.user.name} - About"
    assert "Version: 1.2.3" in embed.description
    assert "Austin Wagner" in embed.fields[0].value
    assert kwargs["ephemeral"] is True
