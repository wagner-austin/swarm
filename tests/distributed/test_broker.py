import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from bot.distributed.broker import Broker


@pytest.mark.asyncio
async def test_ensure_stream_and_group_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange: Patch the Redis connection and xgroup_create
    mock_redis = AsyncMock()
    mock_redis.xgroup_create = AsyncMock()

    # Create broker with proper redis_url and patch the internal redis connection
    broker = Broker(redis_url="redis://localhost:6379/0")
    broker._r = mock_redis

    # Simulate BUSYGROUP error on second call
    mock_redis.xgroup_create.side_effect = [
        None,
        Exception("BUSYGROUP Consumer Group name already exists"),
    ]

    # Act: Call twice with required group parameter (should not raise)
    await broker.ensure_stream_and_group("all-workers")
    await broker.ensure_stream_and_group("all-workers")

    # Assert: xgroup_create called twice, BUSYGROUP error handled
    assert mock_redis.xgroup_create.call_count == 2


@pytest.mark.asyncio
async def test_ensure_stream_and_group_other_error(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_redis = AsyncMock()
    mock_redis.xgroup_create = AsyncMock(side_effect=Exception("Some other error"))

    # Create broker with proper redis_url and patch the internal redis connection
    broker = Broker(redis_url="redis://localhost:6379/0")
    broker._r = mock_redis

    with pytest.raises(Exception) as excinfo:
        await broker.ensure_stream_and_group("all-workers")
    assert "Some other error" in str(excinfo.value)
