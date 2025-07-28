#!/usr/bin/env python3
"""Quick test to verify the test compose setup is working correctly."""

import asyncio
import os
import sys

import redis.asyncio as redis

from swarm.infra import async_close_redis


async def test_connections() -> bool:
    """Test that we can connect to Redis through HAProxy without auth."""
    print("Testing Redis connections in test environment...")
    print(f"REDIS_URL: {os.getenv('REDIS_URL', 'not set')}")
    print(f"CELERY_BROKER_URLS: {os.getenv('CELERY_BROKER_URLS', 'not set')}")

    # Test direct Redis connection
    try:
        direct_client = redis.from_url("redis://localhost:6379/0")
        await direct_client.ping()
        print("✅ Direct Redis connection (port 6379): OK")
        await async_close_redis(direct_client)
    except Exception as e:
        print(f"❌ Direct Redis connection failed: {e}")
        return False

    # Test HAProxy connection (should work without auth in test env)
    try:
        haproxy_client = redis.from_url("redis://localhost:6380/0")
        await haproxy_client.ping()
        print("✅ HAProxy Redis connection (port 6380): OK")

        # Test write/read
        await haproxy_client.set("test:key", b"test:value")
        value = await haproxy_client.get("test:key")
        assert value == b"test:value"
        print("✅ HAProxy write/read test: OK")

        await haproxy_client.delete("test:key")
        await async_close_redis(haproxy_client)
    except Exception as e:
        print(f"❌ HAProxy Redis connection failed: {e}")
        return False

    print("\n✅ All connections working correctly!")
    return True


if __name__ == "__main__":
    success = asyncio.run(test_connections())
    sys.exit(0 if success else 1)
