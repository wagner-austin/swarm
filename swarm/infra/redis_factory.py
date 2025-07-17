"""
Factory for creating Redis backends with automatic failover configuration.
"""

import logging
import os
from typing import Any

import redis.asyncio as redis

from swarm.core.settings import Settings
from swarm.infra.redis_backends import (
    FallbackRedisBackend,
    LocalRedisBackend,
    RedisBackend,
    UpstashRedisBackend,
)
from swarm.types import RedisBytes

logger = logging.getLogger(__name__)


def create_redis_backend(settings: Settings | None = None) -> RedisBackend:
    """
    Create a Redis backend with automatic failover between Upstash and local Redis.

    This factory:
    1. Uses the primary Redis URL from settings
    2. Configures a local Redis fallback
    3. Returns a FallbackRedisBackend that handles automatic switching

    Environment variables:
    - REDIS_FALLBACK_URL: URL for fallback Redis (default: redis://localhost:6379/0)
    - REDIS_FALLBACK_ENABLED: Enable automatic fallback (default: true)
    """
    if settings is None:
        settings = Settings()

    primary_url = settings.redis.url
    fallback_enabled = os.getenv("REDIS_FALLBACK_ENABLED", "true").lower() == "true"
    fallback_url = os.getenv("REDIS_FALLBACK_URL", "redis://localhost:6379/0")

    # Detect if primary is Upstash based on URL
    assert primary_url is not None, "Redis URL must be configured"
    is_upstash = "upstash.io" in primary_url

    if is_upstash:
        primary: RedisBackend = UpstashRedisBackend(primary_url)
        logger.info("Configured Upstash as primary Redis backend")
    else:
        primary = LocalRedisBackend(primary_url)
        logger.info("Configured local Redis as primary backend")

    if fallback_enabled and is_upstash:
        # Only use fallback for Upstash to handle rate limits
        fallback = LocalRedisBackend(fallback_url)
        backend = FallbackRedisBackend(primary, fallback)
        logger.info(f"Configured automatic fallback to {fallback_url}")
        return backend
    else:
        return primary


async def create_redis_client(settings: Settings | None = None) -> RedisBytes:
    """
    Create a Redis client using the backend abstraction.

    This is a compatibility layer for existing code that expects a Redis client.
    """

    backend = create_redis_backend(settings)
    await backend.connect()

    # Create a proxy that delegates to the backend
    class RedisBackendProxy:
        def __init__(self, backend: RedisBackend):
            self._backend = backend

        def __getattr__(self, name: str) -> Any:
            async def method(*args: Any, **kwargs: Any) -> Any:
                return await self._backend.execute(name, *args, **kwargs)

            return method

        async def close(self) -> None:
            await self._backend.disconnect()

    return RedisBackendProxy(backend)  # type: ignore
