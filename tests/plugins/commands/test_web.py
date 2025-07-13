from __future__ import annotations

import asyncio
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from bot.core.containers import Container
from bot.plugins.commands.web import Web


@pytest.fixture
def container_with_mocked_infra() -> tuple[Container, AsyncMock, AsyncMock]:
    """Create real DI container with mocked Redis/Broker infrastructure."""
    # Create real container
    container = Container()

    # Mock Redis client
    mock_redis = AsyncMock()
    mock_redis.hgetall.return_value = {b"is_degraded": b"false", b"healthy_workers": b"2"}
    container.redis_client.override(mock_redis)

    # Mock broker - mock the publish_and_wait method
    mock_broker = AsyncMock()
    mock_broker.publish_and_wait.return_value = {
        "success": True,
        "data": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",  # minimal PNG base64
    }
    container.broker.override(mock_broker)

    return container, mock_redis, mock_broker


@pytest.fixture
def dummy_bot(container_with_mocked_infra: tuple[Container, AsyncMock, AsyncMock]) -> MagicMock:
    """Create a mocked bot with real DI container."""
    container, _, _ = container_with_mocked_infra

    bot = MagicMock(spec=discord.ext.commands.Bot)
    bot.container = container
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
async def test_web_start_with_valid_url(
    dummy_bot: MagicMock,
    interaction: MagicMock,
    container_with_mocked_infra: tuple[Container, AsyncMock, AsyncMock],
) -> None:
    """Test /web start command with valid URL - tests real DI container flow."""
    container, mock_redis, mock_broker = container_with_mocked_infra
    mock_safe_send = AsyncMock()
    mock_validate_url = MagicMock(return_value="https://example.com")

    interaction.response.defer = AsyncMock()

    # Create Web cog using REAL DI container factory
    cog = container.web_cog(
        bot=dummy_bot,
        safe_send_func=mock_safe_send,
        validate_url_func=mock_validate_url,
    )

    await cast(Any, cog.start.callback)(cog, interaction, url="https://example.com")

    # Verify the command flow
    interaction.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
    mock_validate_url.assert_called_once_with("https://example.com")
    mock_safe_send.assert_awaited_once()
    assert "Started browser and navigated to" in mock_safe_send.call_args[0][1]

    # Verify real browser runtime was used (via broker)
    mock_broker.publish_and_wait.assert_awaited_once()


@pytest.mark.asyncio
async def test_web_start_command_invalid_url(
    dummy_bot: MagicMock,
    interaction: MagicMock,
    container_with_mocked_infra: tuple[Container, AsyncMock, AsyncMock],
) -> None:
    """Test /web start command with invalid URL (validation error)."""
    container, mock_redis, mock_broker = container_with_mocked_infra
    mock_safe_send = AsyncMock()
    mock_validate_url = MagicMock(side_effect=ValueError("Invalid URL scheme"))

    interaction.response.defer = AsyncMock()

    # Create Web cog using REAL DI container factory
    cog = container.web_cog(
        bot=dummy_bot,
        safe_send_func=mock_safe_send,
        validate_url_func=mock_validate_url,
    )

    await cast(Any, cog.start.callback)(cog, interaction, url="not-a-url")

    interaction.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
    mock_validate_url.assert_called_once_with("not-a-url")
    # Browser method not called due to validation error
    mock_safe_send.assert_awaited_once()
    assert "Invalid URL" in mock_safe_send.call_args[0][1]
    # Verify broker was NOT called due to validation failure
    mock_broker.publish_and_wait.assert_not_called()


@pytest.mark.asyncio
async def test_web_start_without_url(
    dummy_bot: MagicMock,
    interaction: MagicMock,
    container_with_mocked_infra: tuple[Container, AsyncMock, AsyncMock],
) -> None:
    """Test /web start command without URL - tests real browser start flow."""
    container, mock_redis, mock_broker = container_with_mocked_infra
    mock_safe_send = AsyncMock()
    mock_validate_url = MagicMock()

    interaction.response.defer = AsyncMock()

    # Create Web cog using REAL DI container factory
    cog = container.web_cog(
        bot=dummy_bot,
        safe_send_func=mock_safe_send,
        validate_url_func=mock_validate_url,
    )

    await cast(Any, cog.start.callback)(cog, interaction, url=None)

    # Verify the command flow
    interaction.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
    mock_validate_url.assert_not_called()
    mock_safe_send.assert_awaited_once()
    assert "Browser started successfully" in mock_safe_send.call_args[0][1]

    # Verify real browser runtime was used (via broker)
    mock_broker.publish_and_wait.assert_awaited_once()


@pytest.mark.asyncio
async def test_web_screenshot_with_health_check(
    dummy_bot: MagicMock,
    interaction: MagicMock,
    container_with_mocked_infra: tuple[Container, AsyncMock, AsyncMock],
) -> None:
    """Test /web screenshot command with browser health checking."""
    container, mock_redis, mock_broker = container_with_mocked_infra
    mock_safe_send = AsyncMock()

    interaction.response.defer = AsyncMock()
    interaction.user.id = 12345

    # Create Web cog using REAL DI container factory
    cog = container.web_cog(
        bot=dummy_bot,
        safe_send_func=mock_safe_send,
    )

    await cast(Any, cog.screenshot.callback)(cog, interaction, filename="test.png")

    # Verify health check was performed
    mock_redis.hgetall.assert_awaited_once_with("browser:health")

    # Verify command flow
    interaction.response.defer.assert_awaited_once_with(thinking=True)
    mock_safe_send.assert_awaited_once()

    # Verify real browser runtime was used (via broker)
    mock_broker.publish_and_wait.assert_awaited_once()

    # Check that a file was sent (screenshot data from mocked broker)
    send_args = mock_safe_send.call_args
    assert "Screenshot taken" in send_args.kwargs.get("content", "")
    assert "file" in send_args.kwargs


@pytest.mark.asyncio
async def test_web_screenshot_degraded_health(dummy_bot: MagicMock, interaction: MagicMock) -> None:
    """Test /web screenshot command when browser pool is degraded."""
    # Create separate container with degraded health status
    container = Container()

    # Mock Redis client to return degraded status
    mock_redis = AsyncMock()
    mock_redis.hgetall.return_value = {b"is_degraded": b"true", b"healthy_workers": b"0"}
    container.redis_client.override(mock_redis)

    # Mock broker (shouldn't be called due to health check failure)
    mock_broker = AsyncMock()
    container.broker.override(mock_broker)

    # Update bot container
    dummy_bot.container = container

    mock_safe_send = AsyncMock()
    interaction.response.defer = AsyncMock()
    interaction.user.id = 12345

    # Create Web cog using REAL DI container factory
    cog = container.web_cog(
        bot=dummy_bot,
        safe_send_func=mock_safe_send,
    )

    await cast(Any, cog.screenshot.callback)(cog, interaction, filename="test.png")

    # Verify health check was performed
    mock_redis.hgetall.assert_awaited_once_with("browser:health")

    # Verify command was deferred but failed fast
    interaction.response.defer.assert_awaited_once_with(thinking=True)
    mock_safe_send.assert_awaited_once()

    # Verify screenshot was NOT taken due to health check failure
    mock_broker.publish_and_wait.assert_not_called()

    # Check that error message was sent
    send_args = mock_safe_send.call_args
    assert "Browser workers are currently unavailable" in send_args.args[1]
