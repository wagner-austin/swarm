from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock

import fakeredis.aioredis as fakeredis_aioredis
import pytest

from swarm.core.containers import Container
from swarm.distributed.celery_browser import CeleryBrowserRuntime
from swarm.infra.redis_keys import HEALTH_KEY
from swarm.infra.redis_protocols import RedisAsyncProtocol, wrap_redis_async
from tests.fakes.fake_discord import FakeBot, FakeInteraction


@pytest.fixture
def container_with_fakeredis() -> tuple[Container, RedisAsyncProtocol, AsyncMock, FakeBot]:
    """DI container wired with fakeredis and mocked browser runtime."""
    container = Container()

    inner = fakeredis_aioredis.FakeRedis(decode_responses=True)
    fake_redis = wrap_redis_async(inner)
    container.redis_client.override(fake_redis)

    mock_browser = AsyncMock(spec=CeleryBrowserRuntime)
    mock_browser.status.return_value = {
        "active_sessions": 2,
        "sessions": [
            {
                "worker_id": "worker-001",
                "status": "healthy",
                "browser_active": True,
                "page_active": True,
                "url": "https://example.com",
                "uptime": 5.1,
                "sessions": 1,
                "session_id": "discord:dm:1",
            },
            {
                "worker_id": "worker-002",
                "status": "healthy",
                "browser_active": True,
                "page_active": True,
                "url": "https://example.org",
                "uptime": 2.4,
                "sessions": 1,
                "session_id": "discord:dm:1",
            },
        ],
    }
    container.remote_browser.override(mock_browser)

    mock_bot = FakeBot()
    mock_bot.container = container

    return container, fake_redis, mock_browser, mock_bot


@pytest.fixture
def interaction() -> FakeInteraction:
    return FakeInteraction(user_id=42, guild_id=None, channel_id=777, channel_name="dm")


@pytest.mark.asyncio
async def test_web_status_integration_embed_and_health(
    container_with_fakeredis: tuple[Container, RedisAsyncProtocol, AsyncMock, FakeBot],
    interaction: FakeInteraction,
) -> None:
    container, fake_redis, mock_browser, mock_bot = container_with_fakeredis

    # Write a health snapshot
    await fake_redis.hset(
        HEALTH_KEY,
        mapping={
            "healthy_workers": "2",
            "is_degraded": "false",
            "last_check": str(time.time()),
            "min_required": "1",
        },
    )
    # Simulate two healthy heartbeats so live TTL path reports healthy
    from swarm.infra.redis_keys import heartbeat_key

    await fake_redis.hset(heartbeat_key("worker-001"), mapping={"t": str(time.time())})
    await fake_redis.expire(heartbeat_key("worker-001"), 60)
    await fake_redis.hset(heartbeat_key("worker-002"), mapping={"t": str(time.time())})
    await fake_redis.expire(heartbeat_key("worker-002"), 60)

    mock_safe_send = AsyncMock()
    cog = container.web_cog(
        discord_bot=mock_bot,
        safe_send_func=mock_safe_send,
    )

    await cog.status.callback(cog, interaction)

    # Validate embed response
    assert mock_safe_send.await_count >= 1
    _, kwargs = mock_safe_send.await_args
    assert kwargs.get("ephemeral") is True
    embed = kwargs.get("embed")
    assert embed is not None
    fields = {f.get("name"): f.get("value") for f in embed.to_dict().get("fields", [])}
    assert fields.get("Active Sessions") == "2"
    assert "Pool Health" in fields and "Healthy:" in fields["Pool Health"]


@pytest.mark.asyncio
async def test_web_status_integration_no_snapshot_before_start(
    container_with_fakeredis: tuple[Container, RedisAsyncProtocol, AsyncMock, FakeBot],
    interaction: FakeInteraction,
) -> None:
    container, fake_redis, mock_browser, mock_bot = container_with_fakeredis

    # Do not write a health snapshot
    mock_safe_send = AsyncMock()
    cog = container.web_cog(
        discord_bot=mock_bot,
        safe_send_func=mock_safe_send,
    )

    await cog.status.callback(cog, interaction)

    _, kwargs = mock_safe_send.await_args
    embed = kwargs.get("embed")
    assert embed is not None
    fields = {f.get("name"): f.get("value") for f in embed.to_dict().get("fields", [])}
    assert isinstance(fields.get("Pool Health"), str) and fields.get("Pool Health", "").startswith(
        "Degraded:"
    )
    assert kwargs.get("ephemeral") is True
