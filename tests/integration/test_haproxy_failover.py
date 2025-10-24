#!/usr/bin/env python3
"""
Test HAProxy Redis failover functionality.

This script verifies that HAProxy correctly handles Redis failover scenarios
and that Flower continues to work when the primary Redis fails.

Usage:
    python scripts/test_haproxy_failover.py
"""

import asyncio
import json
import time
from typing import Any, cast

import aiohttp
import redis.asyncio as redis
from redis.exceptions import ConnectionError, ResponseError

from swarm.infra import async_close_redis


async def check_redis_connection(host: str, port: int, password: str | None = None) -> bool:
    """Check if Redis is accessible."""
    try:
        client = redis.from_url(
            f"redis://{':' + password + '@' if password else ''}{host}:{port}/0",
            decode_responses=True,
            socket_connect_timeout=2,
        )
        await client.ping()
        await async_close_redis(client)
        return True
    except Exception as e:
        print(f"Redis connection failed ({host}:{port}): {e}")
        return False


async def check_haproxy_stats(host: str = "localhost", port: int = 8080) -> dict[str, Any]:
    """Check HAProxy stats to see backend status."""
    stats: dict[str, Any] = {}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://{host}:{port}/stats;csv") as resp:
                if resp.status == 200:
                    csv_data = await resp.text()
                    lines = csv_data.strip().split("\n")

                    if not lines:
                        print("No data received from HAProxy stats")
                        return stats

                    # Parse headers to create column name -> index mapping
                    headers = lines[0].split(",")
                    header_map = {header.strip(): idx for idx, header in enumerate(headers)}

                    # Validate required columns exist
                    required_columns = ["# pxname", "svname", "status", "check_status"]
                    missing_columns = [col for col in required_columns if col not in header_map]
                    if missing_columns:
                        print(f"Missing required columns in HAProxy stats: {missing_columns}")
                        return stats

                    for line in lines[1:]:
                        fields = line.split(",")
                        if (
                            len(fields) > header_map["svname"]
                            and fields[header_map["# pxname"]] == "redis_backend"
                        ):
                            server_name = fields[header_map["svname"]]
                            status = fields[header_map["status"]]
                            check_status = fields[header_map["check_status"]]

                            stats[server_name] = {
                                "status": status,
                                "check_status": check_status,
                            }
    except Exception as e:
        print(f"Failed to get HAProxy stats: {e}")

    return stats


async def check_flower_api(host: str = "localhost", port: int = 5555) -> bool:
    """Check if Flower API is responsive."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://{host}:{port}/api/workers") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print(f"Flower API working, found {len(data)} workers")
                    return True
    except Exception as e:
        print(f"Flower API check failed: {e}")

    return False


async def simulate_redis_failover() -> None:
    """Simulate Redis failover scenario."""
    print("=== Redis Failover Test with HAProxy ===\n")

    # Step 1: Check initial state
    print("1. Checking initial state...")

    # Check direct Redis connections
    local_redis_ok = await check_redis_connection("localhost", 6379)
    haproxy_redis_ok = await check_redis_connection("localhost", 6380)

    print(f"   Local Redis (6379): {'[OK]' if local_redis_ok else '[FAIL]'}")
    print(f"   HAProxy Redis (6380): {'[OK]' if haproxy_redis_ok else '[FAIL]'}")

    # Check HAProxy stats
    stats = await check_haproxy_stats()
    print("\n   HAProxy backend status:")
    for server, info in stats.items():
        print(f"   - {server}: {info['status']} (check: {info['check_status']})")

    # Check Flower
    flower_ok = await check_flower_api()
    print(f"\n   Flower API: {'[OK]' if flower_ok else '[FAIL]'}")

    # Step 2: Test Redis operations through HAProxy
    print("\n2. Testing Redis operations through HAProxy...")
    try:
        client = redis.from_url("redis://localhost:6380/0", decode_responses=True)

        # Write test data
        test_key = "haproxy:test:key"
        test_value = f"test_value_{int(time.time())}"
        await cast(Any, client).set(test_key, test_value)

        # Read back
        retrieved = await cast(Any, client).get(test_key)
        if retrieved == test_value:
            print("   [OK] Redis read/write through HAProxy successful")
        else:
            print("   [FAIL] Redis read/write failed")

        await async_close_redis(client)
    except Exception as e:
        print(f"   [FAIL] Redis operations failed: {e}")

    # Step 3: Monitor Flower during simulated failures
    print("\n3. Monitoring Flower stability...")
    print("   (In production, you would stop the primary Redis here)")
    print("   HAProxy should automatically failover to the backup server")

    # Check multiple times to ensure stability
    for i in range(3):
        await asyncio.sleep(2)
        flower_ok = await check_flower_api()
        stats = await check_haproxy_stats()

        print(f"\n   Check {i + 1}:")
        print(f"   - Flower API: {'[OK]' if flower_ok else '[FAIL]'}")
        for server, info in stats.items():
            if info["status"] != "no check":
                print(f"   - {server}: {info['status']}")

    print("\n=== Test Complete ===")
    print("\nTo fully test failover:")
    print("1. Stop the primary Redis: docker stop redis")
    print("2. Check HAProxy stats: http://localhost:8080/stats")
    print("3. Verify Flower still works: http://localhost:5555")
    print("4. Restart Redis: docker start redis")
    print("5. Verify HAProxy fails back to primary")


async def main() -> None:
    """Run the failover test."""
    await simulate_redis_failover()


if __name__ == "__main__":
    asyncio.run(main())
