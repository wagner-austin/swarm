"""Tests for BrowserHealthMonitor cog using real DI container."""

import asyncio
import time
from unittest.mock import MagicMock

import fakeredis.aioredis as fakeredis_aioredis
import pytest

from swarm.core.containers import Container
from swarm.infra.redis_keys import HEALTH_KEY, heartbeat_key
from swarm.infra.redis_protocols import RedisAsyncProtocol, wrap_redis_async
from swarm.plugins.monitor.browser_health import BrowserHealthMonitor, read_health_snapshot


@pytest.fixture
def container_with_mocked_redis() -> tuple[Container, MagicMock, RedisAsyncProtocol]:
    """Create real DI container with fakeredis client supporting Lua."""
    container = Container()
    inner = fakeredis_aioredis.FakeRedis(decode_responses=True)
    fake_redis = wrap_redis_async(inner)
    container.redis_client.override(fake_redis)

    mock_discord_bot = MagicMock()
    mock_discord_bot.user = MagicMock(id=1234)
    mock_discord_bot.container = container

    return container, mock_discord_bot, fake_redis


@pytest.mark.asyncio
async def test_browser_health_monitor_creation(
    container_with_mocked_redis: tuple[Container, MagicMock, MagicMock],
) -> None:
    """Test BrowserHealthMonitor cog creation using real DI container."""
    container, mock_discord_bot, fake_redis = container_with_mocked_redis

    # Create BrowserHealthMonitor cog using REAL DI container factory
    cog = container.browser_health_monitor_cog(discord_bot=mock_discord_bot)

    assert isinstance(cog, BrowserHealthMonitor)
    assert cog.redis is fake_redis
    # Check interval was increased to reduce Redis command usage
    assert cog.check_interval == 60.0
    assert cog.min_healthy_workers == 1


@pytest.mark.asyncio
async def test_browser_health_monitor_start_stop_monitoring(
    container_with_mocked_redis: tuple[Container, MagicMock, MagicMock],
) -> None:
    """Test BrowserHealthMonitor cog monitoring task lifecycle."""
    container, mock_discord_bot, fake_redis = container_with_mocked_redis

    # Create BrowserHealthMonitor cog using REAL DI container factory
    cog = container.browser_health_monitor_cog(discord_bot=mock_discord_bot)

    # Initially no monitoring task
    assert cog.monitoring_task is None

    # Start monitoring - test actual task creation
    await cog.cog_load()

    # Should have created a monitoring task
    assert cog.monitoring_task is not None
    assert not cog.monitoring_task.done()

    # Stop monitoring
    await cog.cog_unload()

    # Task should be cleaned up (cancelled and set to None)
    # Give a moment for cleanup to complete
    await asyncio.sleep(0.01)
    assert cog.monitoring_task is None


@pytest.mark.asyncio
async def test_browser_health_check_with_healthy_workers(
    container_with_mocked_redis: tuple[Container, MagicMock, MagicMock],
) -> None:
    """Test health check with healthy workers using Celery ping."""
    container, mock_discord_bot, fake_redis = container_with_mocked_redis

    # Create BrowserHealthMonitor cog using REAL DI container factory
    cog = container.browser_health_monitor_cog(discord_bot=mock_discord_bot)

    # Create two healthy heartbeat keys
    await fake_redis.hset(heartbeat_key("w1"), mapping={"t": str(time.time())})
    await fake_redis.expire(heartbeat_key("w1"), 60)
    await fake_redis.hset(heartbeat_key("w2"), mapping={"t": str(time.time())})
    await fake_redis.expire(heartbeat_key("w2"), 60)

    # Check health
    await cog._check_worker_health()

    health_status = cog.get_health_status()
    is_healthy = not health_status.get("is_degraded", True)

    assert is_healthy is True
    assert health_status["healthy_workers"] == 2
    # Verify snapshot stored in Redis
    snap = await read_health_snapshot(fake_redis)
    assert snap is not None and snap["healthy_workers"] == 2 and snap["healthy"] is True


@pytest.mark.asyncio
async def test_browser_health_check_with_stale_workers(
    container_with_mocked_redis: tuple[Container, MagicMock, MagicMock],
) -> None:
    """Test health check with stale workers."""
    container, mock_discord_bot, fake_redis = container_with_mocked_redis

    # Create BrowserHealthMonitor cog using REAL DI container factory
    cog = container.browser_health_monitor_cog(discord_bot=mock_discord_bot)

    # Check health - should mark as degraded
    await cog._check_worker_health()
    health_status = cog.get_health_status()
    is_healthy = not health_status.get("is_degraded", True)

    assert is_healthy is False
    assert health_status["healthy_workers"] == 0


@pytest.mark.asyncio
async def test_browser_health_check_no_workers(
    container_with_mocked_redis: tuple[Container, MagicMock, MagicMock],
) -> None:
    """Test health check with no workers."""
    container, mock_discord_bot, fake_redis = container_with_mocked_redis

    # Create BrowserHealthMonitor cog using REAL DI container factory
    cog = container.browser_health_monitor_cog(discord_bot=mock_discord_bot)

    # Check health - should mark as degraded
    await cog._check_worker_health()
    health_status = cog.get_health_status()
    is_healthy = not health_status.get("is_degraded", True)

    assert is_healthy is False
    assert health_status["healthy_workers"] == 0
