from __future__ import annotations

import asyncio
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from bot.plugins.commands.web import Web


@pytest.fixture
def dummy_bot() -> MagicMock:
    bot = MagicMock(spec=discord.ext.commands.Bot)
    bot.container = MagicMock()
    return bot


@pytest.fixture
def interaction() -> MagicMock:
    """Create a properly mocked Discord interaction."""
    inter = MagicMock(spec=discord.Interaction)
    inter.user.id = 12345
    inter.channel_id = 67890
    inter.response.defer = AsyncMock()
    inter.response.send_message = AsyncMock()
    inter.followup.send = AsyncMock()
    return inter


@pytest.mark.asyncio
async def test_web_start_with_valid_url(dummy_bot: MagicMock, interaction: MagicMock) -> None:
    """Test /web start command with valid URL - tests input validation and message formatting."""
    mock_safe_send = AsyncMock()
    mock_validate_url = MagicMock(return_value="https://example.com")

    # Mock the browser runtime entirely - we're testing the command logic, not browser integration
    with patch("bot.plugins.commands.web.RemoteBrowserRuntime") as mock_browser_class:
        mock_browser_instance = mock_browser_class.return_value
        mock_browser_instance.goto = AsyncMock()

        interaction.response.defer = AsyncMock()

        cog = Web(
            dummy_bot,
            safe_send_func=mock_safe_send,
            validate_url_func=mock_validate_url,
        )

        await cast(Any, cog.start.callback)(cog, interaction, url="https://example.com")

        # Verify the command flow
        interaction.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
        mock_validate_url.assert_called_once_with("https://example.com")
        mock_browser_instance.goto.assert_awaited_once_with(
            "https://example.com", worker_hint="12345"
        )
        mock_safe_send.assert_awaited_once()
        assert "Started browser and navigated to" in mock_safe_send.call_args[0][1]


@pytest.mark.asyncio
async def test_web_start_command_invalid_url(dummy_bot: MagicMock, interaction: MagicMock) -> None:
    """Test /web start command with invalid URL (validation error)."""
    mock_safe_send = AsyncMock()
    mock_validate_url = MagicMock(side_effect=ValueError("Invalid URL scheme"))

    # No need to mock browser since validation fails before it's used
    with patch("bot.plugins.commands.web.RemoteBrowserRuntime"):
        interaction.response.defer = AsyncMock()

        cog = Web(
            dummy_bot,
            safe_send_func=mock_safe_send,
            validate_url_func=mock_validate_url,
        )

        await cast(Any, cog.start.callback)(cog, interaction, url="not-a-url")

        interaction.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
        mock_validate_url.assert_called_once_with("not-a-url")
        # Browser method not called due to validation error
        mock_safe_send.assert_awaited_once()
        assert "Invalid URL" in mock_safe_send.call_args[0][1]


@pytest.mark.asyncio
async def test_web_start_without_url(dummy_bot: MagicMock, interaction: MagicMock) -> None:
    """Test /web start command without URL - tests browser start flow."""
    mock_safe_send = AsyncMock()
    mock_validate_url = MagicMock()

    # Mock the browser runtime entirely - we're testing the command logic, not browser integration
    with patch("bot.plugins.commands.web.RemoteBrowserRuntime") as mock_browser_class:
        mock_browser_instance = mock_browser_class.return_value
        mock_browser_instance.start = AsyncMock()

        interaction.response.defer = AsyncMock()

        cog = Web(
            dummy_bot,
            safe_send_func=mock_safe_send,
            validate_url_func=mock_validate_url,
        )

        await cast(Any, cog.start.callback)(cog, interaction, url=None)

        # Verify the command flow
        interaction.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
        mock_validate_url.assert_not_called()
        mock_browser_instance.start.assert_awaited_once_with(worker_hint="12345")
        mock_safe_send.assert_awaited_once()
        assert "Browser started successfully" in mock_safe_send.call_args[0][1]
