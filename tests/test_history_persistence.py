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
    """
    Fixture that provides a Redis backend for testing.

    Uses the production Redis infrastructure with automatic failover.
    """
    from swarm.infra.redis_factory import create_redis_backend

    settings = Settings()

    # Check if Redis is enabled in settings
    if not getattr(settings.redis, "enabled", False):
        pytest.skip("Redis is not enabled in test settings")

    # Create backend using the production factory (with automatic failover)
    try:
        infra_backend = create_redis_backend(settings)
        await infra_backend.connect()

        # Get the active URL from the infrastructure backend
        active_url = infra_backend.url

        # Create history backend with the active URL
        backend = RedisBackend(active_url, max_turns=5)

        # Test connection
        await backend.clear(999999, "test_persona")

        yield backend

        # Cleanup
        await backend.clear(999999, "test_persona")
        await infra_backend.disconnect()

    except Exception as e:
        pytest.skip(f"Redis not available: {e}")


@pytest.mark.asyncio
async def test_redis_backend_persists_across_instances(redis_backend: RedisBackend) -> None:
    from swarm.infra.redis_factory import create_redis_backend

    # Simulate writing history in one instance
    channel = 999999
    persona = "test_persona"
    turn1 = ("hello", "world")
    turn2 = ("foo", "bar")
    await redis_backend.record(channel, persona, turn1)
    await redis_backend.record(channel, persona, turn2)

    # Simulate a new instance (new backend object, same Redis)
    # Use the same production factory to get consistent failover behavior
    infra_backend2 = create_redis_backend()
    await infra_backend2.connect()
    active_url2 = infra_backend2.url
    new_backend = RedisBackend(active_url2, max_turns=5)

    history = await new_backend.recent(channel, persona)
    assert history[-2:] == [turn1, turn2], f"Expected last two turns to persist, got: {history}"

    # Clean up
    await new_backend.clear(channel, persona)
    await infra_backend2.disconnect()
