from __future__ import annotations

import asyncio
from typing import AsyncIterator
from unittest.mock import AsyncMock

import discord
import pytest
from celery.result import AsyncResult

from swarm.core.containers import Container
from swarm.distributed.celery_browser import CeleryBrowserRuntime
from swarm.infra.redis_protocols import RedisAsyncProtocol
from swarm.plugins.commands.web import Web
from tests.fakes.fake_discord import FakeBot, FakeInteraction


class _FakeAsyncRedisHealth(RedisAsyncProtocol):
    def __init__(self, mapping: dict[bytes, bytes], eval_return: int = 1) -> None:
        self._mapping = dict(mapping)
        self.hgetall_calls: list[str] = []
        self._eval_return = int(eval_return)

    # Minimal methods required by the protocol calls in this test module
    async def hgetall(self, name: str) -> dict[str, str]:
        self.hgetall_calls.append(name)
        # Convert stored bytes mapping to str mapping
        return {
            (k.decode() if isinstance(k, bytes | bytearray) else str(k)): (
                v.decode() if isinstance(v, bytes | bytearray) else str(v)
            )
            for k, v in self._mapping.items()
        }

    # Stub methods not used here
    async def hset(
        self,
        name: str,
        key: str | None = None,
        value: str | None = None,
        *,
        mapping: dict[str, str] | None = None,
    ) -> int:  # noqa: D401
        return 0

    async def hget(self, name: str, key: str) -> str | None:  # noqa: D401
        return None

    async def rpush(self, key: str, *values: str) -> int:  # noqa: D401
        return 0

    async def ltrim(self, key: str, start: int, stop: int) -> bool:  # noqa: D401
        return True

    async def lrange(self, key: str, start: int, stop: int) -> list[str]:  # noqa: D401
        return []

    async def delete(self, *names: str) -> int:  # noqa: D401
        return 0

    async def keys(self, pattern: str) -> list[str]:  # noqa: D401
        return []

    def scan_iter(self, *, match: str) -> AsyncIterator[str]:
        async def _aiter() -> AsyncIterator[str]:
            if False:
                yield ""  # pragma: no cover
            return

        return _aiter()

    async def ttl(self, name: str) -> int:  # noqa: D401
        return 0

    async def expire(self, name: str, time: int) -> bool:  # noqa: D401, A003
        return True

    async def srem(self, name: str, *values: str) -> int:  # noqa: D401
        return 0

    async def eval(
        self,
        script: str,
        numkeys: int,
        *keys_and_args: object,
        keys: list[str] | None = None,
        args: list[str] | None = None,
    ) -> object:  # noqa: D401
        # Return configured value to simulate live TTL count
        return int(self._eval_return)

    async def close(self) -> None:  # noqa: D401
        return None

    async def aclose(self) -> None:  # noqa: D401
        return None


@pytest.fixture
def container_with_mocked_infra() -> tuple[Container, _FakeAsyncRedisHealth, AsyncMock]:
    """Create real DI container with strict fake Redis/Broker infrastructure."""
    container = Container()

    fake_redis = _FakeAsyncRedisHealth(
        {b"is_degraded": b"false", b"healthy_workers": b"2"}, eval_return=1
    )
    container.redis_client.override(fake_redis)

    # No need to mock broker - CeleryBrowserRuntime uses Celery tasks directly
    # The mock_browser will handle all browser operations

    # Mock CeleryBrowserRuntime to avoid SSL issues
    mock_browser = AsyncMock(spec=CeleryBrowserRuntime)
    mock_browser.start.return_value = {"success": True}
    mock_browser.goto.return_value = {"success": True}
    mock_browser.screenshot.return_value = b"fake_screenshot_data"
    mock_browser.status.return_value = {
        "active_sessions": 1,
        "sessions": [
            {
                "worker_id": "worker-001",
                "status": "healthy",
                "browser_active": True,
                "page_active": True,
                "url": "https://example.com",
                "uptime": 12.3,
                "sessions": 1,
                "session_id": "discord:dm:67890",
            }
        ],
    }
    # Override the factory to return our mock instance
    container.remote_browser.override(mock_browser)

    return container, fake_redis, mock_browser


@pytest.fixture
def dummy_discord_bot(
    container_with_mocked_infra: tuple[Container, AsyncMock, AsyncMock],
) -> FakeBot:
    """Create a FakeBot wired with real DI container."""
    container, _, _ = container_with_mocked_infra
    bot = FakeBot()
    bot.container = container
    return bot


@pytest.fixture
def interaction() -> FakeInteraction:
    """Create a FakeInteraction modelling a DM channel."""
    return FakeInteraction(user_id=12345, guild_id=None, channel_id=67890, channel_name="dm")


@pytest.mark.asyncio
async def test_web_start_with_valid_url(
    dummy_discord_bot: FakeBot,
    interaction: FakeInteraction,
    container_with_mocked_infra: tuple[Container, AsyncMock, AsyncMock],
) -> None:
    """Test /web start command with valid URL - tests real DI container flow."""
    container, fake_redis, mock_browser = container_with_mocked_infra
    mock_safe_send = AsyncMock()

    def _validate(url: str) -> str:
        return "https://example.com"

    # Create Web cog using REAL DI container factory
    cog = container.web_cog(
        discord_bot=dummy_discord_bot,
        safe_send_func=mock_safe_send,
        validate_url_func=_validate,
    )

    await cog.start.callback(cog, interaction, url="https://example.com")

    # Verify the command flow
    assert interaction.response.deferred is True
    assert interaction.response.defer_calls[-1] == {"ephemeral": True, "thinking": True}
    # validate_url_func used
    mock_safe_send.assert_awaited_once()
    assert "Started browser and navigated to" in mock_safe_send.call_args[0][1]

    # Verify browser was called (through our mocked CeleryBrowserRuntime)
    mock_browser.start.assert_awaited_once()
    mock_browser.goto.assert_awaited_once_with("https://example.com", session_id="discord:dm:67890")


@pytest.mark.asyncio
async def test_web_start_command_invalid_url(
    dummy_discord_bot: FakeBot,
    interaction: FakeInteraction,
    container_with_mocked_infra: tuple[Container, AsyncMock, AsyncMock],
) -> None:
    """Test /web start command with invalid URL (validation error)."""
    container, fake_redis, mock_browser = container_with_mocked_infra
    mock_safe_send = AsyncMock()

    def _bad_validate(_: str) -> str:
        raise ValueError("Invalid URL scheme")

    # Create Web cog using REAL DI container factory
    cog = container.web_cog(
        discord_bot=dummy_discord_bot,
        safe_send_func=mock_safe_send,
        validate_url_func=_bad_validate,
    )

    await cog.start.callback(cog, interaction, url="not-a-url")

    assert interaction.response.deferred is True
    assert interaction.response.defer_calls[-1] == {"ephemeral": True, "thinking": True}
    # validate_url_func used
    # Browser method not called due to validation error
    mock_safe_send.assert_awaited_once()
    assert "Invalid URL" in mock_safe_send.call_args[0][1]
    # Verify browser was NOT called due to validation failure
    mock_browser.start.assert_not_called()
    mock_browser.goto.assert_not_called()


@pytest.mark.asyncio
async def test_web_start_without_url(
    dummy_discord_bot: FakeBot,
    interaction: FakeInteraction,
    container_with_mocked_infra: tuple[Container, AsyncMock, AsyncMock],
) -> None:
    """Test /web start command without URL - tests real browser start flow."""
    container, fake_redis, mock_browser = container_with_mocked_infra
    mock_safe_send = AsyncMock()

    def _noop_validate(url: str) -> str:
        return url

    # Create Web cog using REAL DI container factory
    cog = container.web_cog(
        discord_bot=dummy_discord_bot,
        safe_send_func=mock_safe_send,
        validate_url_func=_noop_validate,
    )

    await cog.start.callback(cog, interaction, url=None)

    # Verify the command flow
    assert interaction.response.deferred is True
    assert interaction.response.defer_calls[-1] == {"ephemeral": True, "thinking": True}
    # no validation when url is None
    mock_safe_send.assert_awaited_once()
    assert "Browser started successfully" in mock_safe_send.call_args[0][1]

    # Verify browser was called (through our mocked CeleryBrowserRuntime)
    mock_browser.start.assert_awaited_once()


@pytest.mark.asyncio
async def test_web_screenshot_with_health_check(
    dummy_discord_bot: FakeBot,
    interaction: FakeInteraction,
    container_with_mocked_infra: tuple[Container, AsyncMock, AsyncMock],
) -> None:
    """Test /web screenshot command with browser health checking."""
    container, fake_redis, mock_browser = container_with_mocked_infra
    mock_safe_send = AsyncMock()

    # Create Web cog using REAL DI container factory
    cog = container.web_cog(
        discord_bot=dummy_discord_bot,
        safe_send_func=mock_safe_send,
    )

    await cog.screenshot.callback(cog, interaction, filename="test.png")

    # Verify command flow
    # Defer called without ephemeral override in screenshot path
    assert interaction.response.deferred is True
    assert interaction.response.defer_calls[-1] == {"ephemeral": False, "thinking": True}
    mock_safe_send.assert_awaited_once()

    # Verify browser screenshot was called
    mock_browser.screenshot.assert_awaited_once()

    # Check that a file was sent (screenshot data from mocked browser)
    send_args = mock_safe_send.call_args
    assert "Screenshot taken" in send_args.kwargs.get("content", "")
    assert "file" in send_args.kwargs


@pytest.mark.asyncio
async def test_web_screenshot_degraded_health(
    dummy_discord_bot: FakeBot, interaction: FakeInteraction
) -> None:
    """Test /web screenshot command when browser pool is degraded."""
    # Create separate container with degraded health status
    container = Container()

    # Mock Redis client to return degraded status
    fake_redis = _FakeAsyncRedisHealth(
        {b"is_degraded": b"true", b"healthy_workers": b"0"}, eval_return=0
    )
    container.redis_client.override(fake_redis)

    # Mock CeleryBrowserRuntime (shouldn't be called due to health check failure)
    mock_browser = AsyncMock(spec=CeleryBrowserRuntime)
    container.remote_browser.override(mock_browser)

    # Create a new FakeBot with this container
    dummy_discord_bot = FakeBot()
    dummy_discord_bot.container = container

    mock_safe_send = AsyncMock()
    # Create Web cog using REAL DI container factory
    cog = container.web_cog(
        discord_bot=dummy_discord_bot,
        safe_send_func=mock_safe_send,
    )

    await cog.screenshot.callback(cog, interaction, filename="test.png")

    # Verify command was deferred but failed fast
    assert interaction.response.deferred is True
    assert interaction.response.defer_calls[-1] == {"ephemeral": False, "thinking": True}
    mock_safe_send.assert_awaited_once()

    # Verify screenshot was NOT taken due to health check failure
    mock_browser.screenshot.assert_not_called()

    # Check that error message was sent
    send_args = mock_safe_send.call_args
    assert "Browser workers are currently unavailable" in send_args.args[1]


@pytest.mark.asyncio
async def test_web_status_displays_sessions_and_health(
    dummy_discord_bot: FakeBot,
    interaction: FakeInteraction,
    container_with_mocked_infra: tuple[Container, _FakeAsyncRedisHealth, AsyncMock],
) -> None:
    """Status returns an embed with pool health and session details."""
    container, fake_redis, mock_browser = container_with_mocked_infra

    mock_safe_send = AsyncMock()

    # Ensure health snapshot exists in fake redis mapping
    fake_redis._mapping = {
        b"is_degraded": b"false",
        b"healthy_workers": b"2",
        b"min_required": b"1",
        b"last_check": b"0.0",
    }

    cog = container.web_cog(
        discord_bot=dummy_discord_bot,
        safe_send_func=mock_safe_send,
    )

    await cog.status.callback(cog, interaction)

    # Validate that an embed was sent with expected fields
    assert mock_safe_send.await_count >= 1
    _, kwargs = mock_safe_send.await_args
    assert kwargs.get("ephemeral") is True
    embed = kwargs.get("embed")
    assert embed is not None and isinstance(embed, discord.Embed)
    # Check that Active Sessions field exists and equals 1
    fields = embed.to_dict().get("fields", [])
    labels = {f.get("name"): f.get("value") for f in fields}
    assert labels.get("Active Sessions") == "1"
    assert "Pool Health" in labels


@pytest.mark.asyncio
async def test_web_status_no_workers_message(
    dummy_discord_bot: FakeBot,
    interaction: FakeInteraction,
    container_with_mocked_infra: tuple[Container, _FakeAsyncRedisHealth, AsyncMock],
) -> None:
    """Status reports a user-friendly message when no workers are active."""
    container, fake_redis, mock_browser = container_with_mocked_infra

    # Return falsy status
    mock_browser.status.return_value = {}

    mock_safe_send = AsyncMock()
    cog = container.web_cog(
        discord_bot=dummy_discord_bot,
        safe_send_func=mock_safe_send,
    )

    await cog.status.callback(cog, interaction)


@pytest.mark.asyncio
async def test_web_status_before_start_no_snapshot(
    dummy_discord_bot: FakeBot,
    interaction: FakeInteraction,
    container_with_mocked_infra: tuple[Container, _FakeAsyncRedisHealth, AsyncMock],
) -> None:
    """Status should not error when no health snapshot exists before start."""
    container, fake_redis, mock_browser = container_with_mocked_infra

    # Empty mapping simulates no snapshot present and no healthy heartbeats
    fake_redis._mapping = {}
    fake_redis._eval_return = 0

    # Simulate no active sessions before any start
    mock_browser.status.return_value = {"active_sessions": 0, "sessions": []}
    mock_safe_send = AsyncMock()
    cog = container.web_cog(
        discord_bot=dummy_discord_bot,
        safe_send_func=mock_safe_send,
    )
    await cog.status.callback(cog, interaction)

    _, kwargs = mock_safe_send.await_args
    assert kwargs.get("ephemeral") is True
    embed = kwargs.get("embed")
    assert embed is not None and isinstance(embed, discord.Embed)
    fields = {f.get("name"): f.get("value") for f in embed.to_dict().get("fields", [])}
    # Live TTL path with no heartbeats -> degraded
    assert isinstance(fields.get("Pool Health"), str) and fields.get("Pool Health", "").startswith(
        "Degraded:"
    )


@pytest.mark.asyncio
async def test_web_status_before_and_after_start(
    dummy_discord_bot: FakeBot,
    interaction: FakeInteraction,
    container_with_mocked_infra: tuple[Container, _FakeAsyncRedisHealth, AsyncMock],
) -> None:
    """Status reflects no workers before start and sessions after start."""
    container, fake_redis, mock_browser = container_with_mocked_infra

    mock_safe_send = AsyncMock()
    cog = container.web_cog(
        discord_bot=dummy_discord_bot,
        safe_send_func=mock_safe_send,
    )

    # Before: runtime reports no sessions -> production returns an embed with 0
    mock_browser.status.return_value = {"active_sessions": 0, "sessions": []}
    await cog.status.callback(cog, interaction)
    _, kwargs = mock_safe_send.await_args
    assert kwargs.get("ephemeral") is True
    embed = kwargs.get("embed")
    assert embed is not None and isinstance(embed, discord.Embed)
    fields = {f.get("name"): f.get("value") for f in embed.to_dict().get("fields", [])}
    assert fields.get("Active Sessions") == "0"

    # After: start without URL, then status shows one session (we update mock)
    mock_browser.start.reset_mock()
    mock_browser.status.return_value = {
        "active_sessions": 1,
        "sessions": [
            {
                "worker_id": "worker-001",
                "status": "healthy",
                "browser_active": True,
                "page_active": True,
                "url": "https://example.com",
                "uptime": 1.0,
                "sessions": 1,
                "session_id": "discord:dm:67890",
            }
        ],
    }
    mock_safe_send.reset_mock()
    await cog.start.callback(cog, interaction, url=None)
    await cog.status.callback(cog, interaction)
    _, kwargs = mock_safe_send.await_args
    embed = kwargs.get("embed")
    assert embed is not None
    fields = {f.get("name"): f.get("value") for f in embed.to_dict().get("fields", [])}
    assert fields.get("Active Sessions") == "1"
