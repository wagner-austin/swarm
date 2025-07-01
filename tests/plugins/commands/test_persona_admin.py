from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from discord import Attachment, Object

from bot.plugins.commands.persona_admin import PersonaAdmin


@pytest.fixture
def mock_bot() -> MagicMock:
    """Fixture for a mock bot instance."""
    bot = MagicMock()
    bot.owner_id = 12345
    bot.is_owner = AsyncMock(return_value=True)
    bot.application_info = AsyncMock()
    bot.application_info.return_value.owner = Object(id=12345)
    return bot


@pytest.fixture
def persona_admin_cog(mock_bot: MagicMock) -> PersonaAdmin:
    """Fixture for the PersonaAdmin cog instance."""
    return PersonaAdmin(bot=mock_bot)


@pytest.mark.asyncio
@patch("bot.plugins.commands.persona_admin.PERSONALITIES", {"test1": {}, "test2": {}})
@patch("bot.plugins.commands.persona_admin._CUSTOM_DIR")
async def test_list_cmd(
    mock_custom_dir: MagicMock,
    persona_admin_cog: PersonaAdmin,
) -> None:
    """Test that the list command shows all personas."""
    mock_interaction = AsyncMock()

    # Mock the path operations properly
    def mock_truediv(filename: str) -> MagicMock:
        mock_path = MagicMock()
        mock_path.exists.return_value = filename == "test1.yaml"
        return mock_path

    mock_custom_dir.__truediv__.side_effect = mock_truediv

    await cast(Any, persona_admin_cog.list_cmd.callback)(persona_admin_cog, mock_interaction)

    mock_interaction.response.send_message.assert_called_once()
    message_content = mock_interaction.response.send_message.call_args[0][0]
    assert "• **test1**  (custom)" in message_content
    assert "• **test2**  (built-in)" in message_content


@pytest.mark.asyncio
@patch(
    "bot.plugins.commands.persona_admin.PERSONALITIES",
    {"test1": {"prompt": "Hello", "allowed_users": [123]}},
)
async def test_show_cmd_found(persona_admin_cog: PersonaAdmin) -> None:
    """Test showing a persona that exists."""
    mock_interaction = AsyncMock()
    await cast(Any, persona_admin_cog.show_cmd.callback)(
        persona_admin_cog, mock_interaction, name="test1"
    )
    mock_interaction.response.send_message.assert_called_once()
    message_content = mock_interaction.response.send_message.call_args[0][0]
    assert "**test1**" in message_content
    assert "Hello" in message_content


@pytest.mark.asyncio
@patch("bot.ai.personas.refresh", new_callable=MagicMock)
@patch("bot.ai.personas.PERSONALITIES", {"test1": {}}, create=True)
async def test_reload_cmd(mock_refresh: MagicMock, persona_admin_cog: PersonaAdmin) -> None:
    """Test that the reload command refreshes personas from disk."""
    mock_interaction = AsyncMock()

    await cast(Any, persona_admin_cog.reload_cmd.callback)(persona_admin_cog, mock_interaction)

    mock_interaction.response.defer.assert_called_once_with(ephemeral=True, thinking=True)
    mock_refresh.assert_called_once()
    mock_interaction.followup.send.assert_called_once_with(
        "Reloaded 1 personas from disk.",
        ephemeral=True,
    )
