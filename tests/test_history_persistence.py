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

    settings = Settings()

    # Check if Redis is enabled in settings
    if not getattr(settings.redis, "enabled", False):
        pytest.skip("Redis is not enabled in test settings")

    # Create backend using test Redis URL when in test environment
    try:
        # Use test Redis URL from environment or default to local Redis with auth
        password = os.getenv("REDIS_PASSWORD", "")
        auth_part = f"default:{password}@" if password else ""
        test_redis_url = os.getenv("REDIS_URL", f"redis://{auth_part}localhost:6379/0")

        # Create history backend with test URL
        backend = RedisBackend(test_redis_url, max_turns=5)

        # Test connection
        await backend.clear(999999, "test_persona")

        yield backend

        # Cleanup
        await backend.clear(999999, "test_persona")

    except Exception as e:
        pytest.skip(f"Redis not available: {e}")


@pytest.mark.asyncio
async def test_redis_backend_persists_across_instances(redis_backend: RedisBackend) -> None:
    """Test that history persists across different backend instances.

    This test verifies that Redis persistence works correctly by creating
    two separate backend instances that connect to the same Redis server.
    """
    # Get the URL from the existing backend to ensure consistency
    redis_url = redis_backend.url

    # Simulate writing history in one instance
    channel = 999999
    persona = "test_persona"
    turn1 = ("hello", "world")
    turn2 = ("foo", "bar")

    await redis_backend.record(channel, persona, turn1)
    await redis_backend.record(channel, persona, turn2)

    # Simulate a new instance using the same Redis URL
    new_backend = RedisBackend(redis_url, max_turns=5)

    history = await new_backend.recent(channel, persona)
    assert history[-2:] == [turn1, turn2], f"Expected last two turns to persist, got: {history}"

    # Clean up
    await new_backend.clear(channel, persona)
