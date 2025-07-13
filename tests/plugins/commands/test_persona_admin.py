from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from discord import Attachment, Object

from bot.core.containers import Container


@pytest.fixture
def container_with_bot() -> tuple[Container, MagicMock]:
    """Create real DI container with mocked bot."""
    container = Container()

    # Mock bot
    bot = MagicMock()
    bot.owner_id = 12345
    bot.is_owner = AsyncMock(return_value=True)
    bot.application_info = AsyncMock()
    bot.application_info.return_value.owner = Object(id=12345)
    bot.container = container

    return container, bot


@pytest.mark.asyncio
@patch("bot.plugins.commands.persona_admin.PERSONALITIES", {"test1": {}, "test2": {}})
@patch("bot.plugins.commands.persona_admin._CUSTOM_DIR")
async def test_list_cmd(
    mock_custom_dir: MagicMock,
    container_with_bot: tuple[Container, MagicMock],
) -> None:
    """Test that the list command shows all personas using real DI container."""
    container, mock_bot = container_with_bot

    # Create PersonaAdmin cog using REAL DI container factory
    mock_safe_send = AsyncMock()
    cog = container.persona_admin_cog(bot=mock_bot, safe_send_func=mock_safe_send)
    mock_interaction = AsyncMock()

    # Mock the path operations properly
    def mock_truediv(filename: str) -> MagicMock:
        mock_path = MagicMock()
        mock_path.exists.return_value = filename == "test1.yaml"
        return mock_path

    mock_custom_dir.__truediv__.side_effect = mock_truediv

    await cast(Any, cog.list_cmd.callback)(cog, mock_interaction)

    mock_safe_send.assert_awaited_once()
    message_content = mock_safe_send.call_args[0][1]
    assert "• **test1**  (custom)" in message_content
    assert "• **test2**  (built-in)" in message_content


@pytest.mark.asyncio
@patch(
    "bot.plugins.commands.persona_admin.PERSONALITIES",
    {"test1": {"prompt": "Hello", "allowed_users": [123]}},
)
async def test_show_cmd_found(container_with_bot: tuple[Container, MagicMock]) -> None:
    """Test showing a persona that exists using real DI container."""
    container, mock_bot = container_with_bot

    # Create PersonaAdmin cog using REAL DI container factory
    mock_safe_send = AsyncMock()
    cog = container.persona_admin_cog(bot=mock_bot, safe_send_func=mock_safe_send)
    mock_interaction = AsyncMock()
    await cast(Any, cog.show_cmd.callback)(cog, mock_interaction, name="test1")
    mock_safe_send.assert_awaited_once()
    message_content = mock_safe_send.call_args[0][1]
    assert "**test1**" in message_content
    assert "Hello" in message_content


@pytest.mark.asyncio
@patch("bot.ai.personas.refresh", new_callable=MagicMock)
@patch("bot.ai.personas.PERSONALITIES", {"test1": {}}, create=True)
async def test_reload_cmd(
    mock_refresh: MagicMock, container_with_bot: tuple[Container, MagicMock]
) -> None:
    """Test that the reload command refreshes personas from disk using real DI container."""
    container, mock_bot = container_with_bot

    # Create PersonaAdmin cog using REAL DI container factory
    mock_safe_send = AsyncMock()
    cog = container.persona_admin_cog(bot=mock_bot, safe_send_func=mock_safe_send)
    mock_interaction = AsyncMock()

    await cast(Any, cog.reload_cmd.callback)(cog, mock_interaction)

    mock_interaction.response.defer.assert_called_once_with(ephemeral=True, thinking=True)
    mock_refresh.assert_called_once()
    # PersonaAdmin now uses safe_send for this response
    # So we need to check the injected safe_send mock
    # The message is the second positional argument
    mock_safe_send.assert_awaited_once()
    message_content = mock_safe_send.call_args[0][1]
    assert "Reloaded 1 personas from disk." in message_content
