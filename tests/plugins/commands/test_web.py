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
async def test_web_start_command_success(dummy_bot: MagicMock, interaction: MagicMock) -> None:
    """Test successful /web start command with valid URL."""
    # Mock dependencies
    mock_browser_runtime = MagicMock()
    # Mock enqueue to return a completed future
    mock_future: asyncio.Future[None] = asyncio.Future()
    mock_future.set_result(None)
    mock_browser_runtime.enqueue = AsyncMock(return_value=mock_future)

    mock_safe_send = AsyncMock()
    mock_validate_url = MagicMock(return_value="https://example.com")

    # Create the Web cog with DI
    cog = Web(
        dummy_bot,
        browser_runtime=mock_browser_runtime,
        safe_send_func=mock_safe_send,
        validate_url_func=mock_validate_url,
    )

    # Mock the safe_defer and safe_send functions that the decorator uses
    with (
        patch("bot.webapi.decorators.safe_defer", new_callable=AsyncMock) as mock_safe_defer,
        patch(
            "bot.webapi.decorators.safe_send", new_callable=AsyncMock
        ) as mock_decorator_safe_send,
    ):
        # Call the start command (this calls the decorator wrapper)
        await cast(Any, cog.start.callback)(cog, interaction, url="https://example.com")

        # Assert validate_url was called
        mock_validate_url.assert_called_once_with("https://example.com")

        # Assert safe_defer was called by decorator
        mock_safe_defer.assert_called_once()

        # Assert browser runtime was called
        mock_browser_runtime.enqueue.assert_called_once_with(67890, "goto", "https://example.com")

        # Assert success message was sent by decorator
        mock_decorator_safe_send.assert_called_once()
        call_args = mock_decorator_safe_send.call_args[0]
        assert "Started browser and navigated to" in call_args[1]


@pytest.mark.asyncio
async def test_web_start_command_invalid_url(dummy_bot: MagicMock, interaction: MagicMock) -> None:
    """Test /web start command with invalid URL (validation error)."""
    # Mock dependencies
    mock_browser_runtime = MagicMock()
    mock_safe_send = AsyncMock()
    mock_validate_url = MagicMock(side_effect=ValueError("Invalid URL scheme"))

    # Create the Web cog with DI
    cog = Web(
        dummy_bot,
        browser_runtime=mock_browser_runtime,
        safe_send_func=mock_safe_send,
        validate_url_func=mock_validate_url,
    )

    # Call the start command with invalid URL (this calls the decorator wrapper)
    await cast(Any, cog.start.callback)(cog, interaction, url="not-a-url")

    # Assert validate_url was called and raised ValueError
    mock_validate_url.assert_called_once_with("not-a-url")

    # Assert interaction.response.send_message was called directly (error case)
    assert interaction.response.send_message.await_count > 0

    # Get the call arguments - they could be positional or keyword
    call_args, call_kwargs = interaction.response.send_message.call_args

    # Check for content in either positional args or keyword args
    if call_args:
        content = call_args[0]  # First positional arg should be content
    else:
        content = call_kwargs.get("content", "")

    assert "Invalid URL" in content

    # Check ephemeral flag in kwargs
    assert call_kwargs.get("ephemeral") is True

    # Assert browser runtime was NOT called in error case
    mock_browser_runtime.enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_web_start_command_no_url(dummy_bot: MagicMock, interaction: MagicMock) -> None:
    """Test /web start command without URL (just start browser)."""
    # Mock dependencies
    mock_browser_runtime = MagicMock()
    mock_future: asyncio.Future[None] = asyncio.Future()
    mock_future.set_result(None)
    mock_browser_runtime.enqueue = AsyncMock(return_value=mock_future)

    mock_safe_send = AsyncMock()
    mock_validate_url = MagicMock()  # Should not be called

    # Create the Web cog with DI
    cog = Web(
        dummy_bot,
        browser_runtime=mock_browser_runtime,
        safe_send_func=mock_safe_send,
        validate_url_func=mock_validate_url,
    )

    # Mock the decorator functions
    with (
        patch("bot.webapi.decorators.safe_defer", new_callable=AsyncMock) as mock_safe_defer,
        patch(
            "bot.webapi.decorators.safe_send", new_callable=AsyncMock
        ) as mock_decorator_safe_send,
    ):
        # Call the start command without URL
        await cast(Any, cog.start.callback)(cog, interaction, url=None)

        # Assert validate_url was NOT called
        mock_validate_url.assert_not_called()

        # Assert safe_defer was called by decorator
        mock_safe_defer.assert_called_once()

        # Assert browser runtime was called with health_check
        mock_browser_runtime.enqueue.assert_called_once_with(67890, "health_check")

        # Assert success message was sent
        mock_decorator_safe_send.assert_called_once()
        call_args = mock_decorator_safe_send.call_args[0]
        assert "Browser started successfully" in call_args[1]
