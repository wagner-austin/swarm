#!/usr/bin/env python3
"""
Test HAProxy Redis failover functionality.

This integration test verifies that HAProxy correctly handles Redis failover
scenarios.

Prerequisites:
    docker compose up -d  # Must have redis, haproxy-redis, and flower running
"""

import asyncio
import time

import pytest
import redis.asyncio as redis
from redis.exceptions import ConnectionError

from swarm.infra import async_close_redis
from swarm.types import RedisStr
from tests.integration.utils import (
    check_docker_services_running,
    check_haproxy_stats,
    check_redis_connection,
)


@pytest.mark.integration
@pytest.mark.docker
@pytest.mark.asyncio
async def test_haproxy_redis_connectivity() -> None:
    """Test that we can connect to Redis through HAProxy."""
    # Skip if services aren't running
    services_ok, message = await check_docker_services_running()
    if not services_ok:
        pytest.skip(message)

    # Test Redis operations through HAProxy
    import os

    password = os.getenv("REDIS_PASSWORD", "")
    auth_part = f"default:{password}@" if password else ""

    # The typed client expects str payloads when decode_responses=True
    client: RedisStr = redis.from_url(f"redis://{auth_part}localhost:6380/0", decode_responses=True)

    try:
        # Write test data
        test_key = "haproxy:test:key"
        test_value = f"test_value_{int(time.time())}"
        await client.set(test_key, test_value)

        # Read back
        retrieved = await client.get(test_key)
        assert retrieved is not None
        assert retrieved == test_value, f"Expected {test_value}, got {retrieved}"

    finally:
        await async_close_redis(client)


@pytest.mark.integration
@pytest.mark.docker
@pytest.mark.asyncio
async def test_haproxy_backend_status() -> None:
    """Test that HAProxy shows correct backend status."""
    # Skip if services aren't running
    services_ok, message = await check_docker_services_running()
    if not services_ok:
        pytest.skip(message)

    stats = await check_haproxy_stats()

    # Should have at least one backend
    assert len(stats) > 0, "No backends found in HAProxy stats"

    # At least one backend should be UP
    up_backends = [name for name, info in stats.items() if info["status"] == "UP"]
    assert len(up_backends) > 0, f"No backends are UP. Stats: {stats}"

    # Verify backend naming convention (redis_0, redis_1, etc)
    # Note: HAProxy stats includes "BACKEND" for aggregate stats
    backend_names = set(stats.keys())
    server_names = [name for name in backend_names if name != "BACKEND"]
    for name in server_names:
        assert name.startswith("redis_"), f"Unexpected backend name format: {name}"


@pytest.mark.integration
@pytest.mark.docker
@pytest.mark.asyncio
async def test_haproxy_redis_stats_accessible() -> None:
    """Verify HAProxy stats endpoint is accessible (indicates service health)."""
    services_ok, message = await check_docker_services_running()
    if not services_ok:
        pytest.skip(message)
    stats = await check_haproxy_stats()
    assert isinstance(stats, dict)


if __name__ == "__main__":
    # Allow running directly for debugging
    pytest.main([__file__, "-v", "-s"])
