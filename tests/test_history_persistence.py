import asyncio
import os
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio

from swarm.core.settings import Settings
from swarm.history.factory import choose as history_backend_factory
from swarm.history.redis_backend import RedisBackend


@pytest_asyncio.fixture(scope="function")
async def redis_backend() -> AsyncGenerator[RedisBackend, None]:
    settings = Settings()
    url = getattr(settings.redis, "url", None)
    if not getattr(settings.redis, "enabled", False) or not isinstance(url, str) or not url:
        pytest.skip("Redis is not enabled or url is invalid in test settings")
    backend = RedisBackend(url, max_turns=5)
    try:
        await backend.clear(999999, "test_persona")
    except Exception as e:
        if "max requests limit exceeded" in str(e):
            pytest.skip(f"Redis rate limit exceeded: {e}")
        raise
    yield backend
    try:
        await backend.clear(999999, "test_persona")
    except Exception:
        # Best effort cleanup, ignore errors
        pass


@pytest.mark.asyncio
async def test_redis_backend_persists_across_instances(redis_backend: RedisBackend) -> None:
    # Simulate writing history in one instance
    channel = 999999
    persona = "test_persona"
    turn1 = ("hello", "world")
    turn2 = ("foo", "bar")
    await redis_backend.record(channel, persona, turn1)
    await redis_backend.record(channel, persona, turn2)

    # Simulate a new instance (new backend object, same Redis)
    settings = Settings()
    url = getattr(settings.redis, "url", None)
    assert isinstance(url, str) and url, "Test requires a valid Redis URL"
    new_backend = RedisBackend(url, max_turns=5)
    history = await new_backend.recent(channel, persona)
    assert history[-2:] == [turn1, turn2], f"Expected last two turns to persist, got: {history}"

    # Clean up
    await new_backend.clear(channel, persona)
