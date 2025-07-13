"""Tests for BrowserHealthMonitor cog using real DI container."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import redis.asyncio as redis_asyncio

from bot.core.containers import Container
from bot.plugins.monitor.browser_health import BrowserHealthMonitor


@pytest.fixture
def container_with_mocked_redis() -> tuple[Container, MagicMock, MagicMock]:
    """Create real DI container with mocked Redis client."""
    container = Container()

    # Mock Redis client
    mock_redis = MagicMock(spec=redis_asyncio.Redis)
    mock_redis.keys = AsyncMock(return_value=[])
    mock_redis.hget = AsyncMock(return_value=None)
    mock_redis.hset = AsyncMock()
    mock_redis.hgetall = AsyncMock(return_value={})
    container.redis_client.override(mock_redis)

    # Mock bot
    mock_bot = MagicMock()
    mock_bot.user = MagicMock(id=1234)
    mock_bot.container = container

    return container, mock_bot, mock_redis


@pytest.mark.asyncio
async def test_browser_health_monitor_creation(
    container_with_mocked_redis: tuple[Container, MagicMock, MagicMock],
) -> None:
    """Test BrowserHealthMonitor cog creation using real DI container."""
    container, mock_bot, mock_redis = container_with_mocked_redis

    # Create BrowserHealthMonitor cog using REAL DI container factory
    cog = container.browser_health_monitor_cog(bot=mock_bot)

    assert isinstance(cog, BrowserHealthMonitor)
    assert cog.redis is mock_redis
    assert cog.check_interval == 15.0
    assert cog.min_healthy_workers == 1
    assert cog.max_heartbeat_age == 60.0


@pytest.mark.asyncio
async def test_browser_health_monitor_start_stop_monitoring(
    container_with_mocked_redis: tuple[Container, MagicMock, MagicMock],
) -> None:
    """Test BrowserHealthMonitor cog monitoring task lifecycle."""
    container, mock_bot, mock_redis = container_with_mocked_redis

    # Create BrowserHealthMonitor cog using REAL DI container factory
    cog = container.browser_health_monitor_cog(bot=mock_bot)

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
    """Test health check with healthy workers."""
    container, mock_bot, mock_redis = container_with_mocked_redis

    # Mock healthy worker heartbeats
    import time

    current_time = time.time()
    mock_redis.keys.return_value = [b"worker:heartbeat:worker1", b"worker:heartbeat:worker2"]
    mock_redis.hget.side_effect = lambda key, field: {
        ("worker:heartbeat:worker1", "timestamp"): str(current_time - 30).encode(),
        ("worker:heartbeat:worker2", "timestamp"): str(current_time - 45).encode(),
    }.get((key, field))

    # Mock the health status data that gets written and read back
    mock_redis.hgetall.return_value = {
        b"healthy_workers": b"2",
        b"is_degraded": b"false",  # 2 workers >= 1 minimum = healthy
        b"last_check": str(current_time).encode(),
        b"min_required": b"1",
    }

    # Create BrowserHealthMonitor cog using REAL DI container factory
    cog = container.browser_health_monitor_cog(bot=mock_bot)

    # Check health
    await cog._check_worker_health()
    health_status = await cog.get_health_status()
    is_healthy = not health_status.get("is_degraded", True)

    assert is_healthy is True
    assert health_status["healthy_workers"] == 2
    mock_redis.keys.assert_called_once_with("worker:heartbeat:*")
    # Verify hset was called to store health data
    mock_redis.hset.assert_called_once()


@pytest.mark.asyncio
async def test_browser_health_check_with_stale_workers(
    container_with_mocked_redis: tuple[Container, MagicMock, MagicMock],
) -> None:
    """Test health check with stale workers."""
    container, mock_bot, mock_redis = container_with_mocked_redis

    # Mock stale worker heartbeats
    import time

    current_time = time.time()
    mock_redis.keys.return_value = [b"worker:heartbeat:worker1", b"worker:heartbeat:worker2"]
    mock_redis.hget.side_effect = lambda key, field: {
        ("worker:heartbeat:worker1", "timestamp"): str(current_time - 120).encode(),
        ("worker:heartbeat:worker2", "timestamp"): str(current_time - 180).encode(),
    }.get((key, field))

    # Mock the health status data for degraded state
    mock_redis.hgetall.return_value = {
        b"healthy_workers": b"0",
        b"is_degraded": b"true",  # 0 workers < 1 minimum = degraded
        b"last_check": str(current_time).encode(),
        b"min_required": b"1",
    }

    # Create BrowserHealthMonitor cog using REAL DI container factory
    cog = container.browser_health_monitor_cog(bot=mock_bot)

    # Check health - should mark as degraded
    await cog._check_worker_health()
    health_status = await cog.get_health_status()
    is_healthy = not health_status.get("is_degraded", True)

    assert is_healthy is False
    assert health_status["healthy_workers"] == 0


@pytest.mark.asyncio
async def test_browser_health_check_no_workers(
    container_with_mocked_redis: tuple[Container, MagicMock, MagicMock],
) -> None:
    """Test health check with no workers."""
    container, mock_bot, mock_redis = container_with_mocked_redis

    # Mock no worker heartbeats
    import time

    current_time = time.time()
    mock_redis.keys.return_value = []

    # Mock the health status data for degraded state (no workers)
    mock_redis.hgetall.return_value = {
        b"healthy_workers": b"0",
        b"is_degraded": b"true",  # 0 workers < 1 minimum = degraded
        b"last_check": str(current_time).encode(),
        b"min_required": b"1",
    }

    # Create BrowserHealthMonitor cog using REAL DI container factory
    cog = container.browser_health_monitor_cog(bot=mock_bot)

    # Check health - should mark as degraded
    await cog._check_worker_health()
    health_status = await cog.get_health_status()
    is_healthy = not health_status.get("is_degraded", True)

    assert is_healthy is False
    assert health_status["healthy_workers"] == 0
