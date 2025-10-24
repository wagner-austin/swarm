"""
Shared utilities for integration tests.

Provides consistent service availability checking and skip messages.
"""

import asyncio
import os
import subprocess
from typing import Any

import aiohttp
import pytest
import redis.asyncio as redis

from swarm.infra import async_close_redis


async def check_haproxy_redis_connection(host: str, port: int, password: str | None = None) -> bool:
    """Check if HAProxy Redis is accessible (connect with auth in URL)."""
    client = None
    try:
        print(f"[DEBUG] Checking HAProxy Redis at {host}:{port}")

        # Build URL with ACL credentials so AUTH is sent in the first packet
        url = (
            f"redis://default:{password}@{host}:{port}/0"
            if password
            else f"redis://{host}:{port}/0"
        )
        client = redis.from_url(url, decode_responses=True, socket_connect_timeout=2)

        # If the URL contained creds, ping succeeds immediately
        await client.ping()
        print("[DEBUG] [OK] Connected to HAProxy Redis")
        return True
    except Exception as e:
        print(f"[DEBUG] [FAIL] Failed to connect to HAProxy Redis at {host}:{port}: {e}")
        return False
    finally:
        if client:
            await async_close_redis(client)


async def check_redis_connection(host: str, port: int, password: str | None = None) -> bool:
    """Check if Redis is accessible."""
    try:
        # Build the URL with proper authentication format
        if password:
            url = f"redis://default:{password}@{host}:{port}/0"
        else:
            url = f"redis://{host}:{port}/0"

        # Debug output
        print(f"[DEBUG] Checking Redis at {host}:{port}, password={'YES' if password else 'NO'}")

        client = redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=2,
        )
        await client.ping()
        await async_close_redis(client)
        print(f"[DEBUG] [OK] Connected to Redis at {host}:{port}")
        return True
    except Exception as e:
        print(f"[DEBUG] [FAIL] Failed to connect to Redis at {host}:{port}: {e}")
        return False


async def check_haproxy_stats(host: str = "localhost", port: int = 8080) -> dict[str, Any]:
    """Check HAProxy stats to see backend status."""
    stats: dict[str, Any] = {}
    try:
        print(f"[DEBUG] Checking HAProxy stats at {host}:{port}")
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://{host}:{port}/stats;csv") as resp:
                if resp.status == 200:
                    csv_data = await resp.text()
                    lines = csv_data.strip().split("\n")

                    if not lines:
                        return stats

                    # Parse headers to create column name -> index mapping
                    headers = lines[0].split(",")
                    header_map = {header.strip(): idx for idx, header in enumerate(headers)}

                    # Validate required columns exist
                    required_columns = ["# pxname", "svname", "status", "check_status"]
                    missing_columns = [col for col in required_columns if col not in header_map]
                    if missing_columns:
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
                print(f"[DEBUG] [OK] HAProxy stats retrieved: {len(stats)} backends")
    except Exception as e:
        print(f"[DEBUG] [FAIL] Failed to get HAProxy stats: {e}")

    return stats


async def check_flower_api(host: str = "localhost", port: int = 5555) -> bool:
    """Check if Flower API is responsive."""
    try:
        print(f"[DEBUG] Checking Flower API at {host}:{port}")
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://{host}:{port}/api/workers") as resp:
                if resp.status == 200:
                    await resp.json()
                    print("[DEBUG] [OK] Flower API is responsive")
                    return True
                else:
                    print(f"[DEBUG] [FAIL] Flower API returned status {resp.status}")
    except Exception as e:
        print(f"[DEBUG] [FAIL] Failed to connect to Flower API: {e}")

    return False


def is_running_in_docker() -> bool:
    """Check if the current process is running inside a Docker container."""
    return os.path.exists("/.dockerenv") or os.getenv("HOSTNAME", "").startswith("docker")


def check_docker_daemon() -> bool:
    """Check if Docker daemon is accessible."""
    try:
        result = subprocess.run(["docker", "ps"], capture_output=True, text=True, check=False)
        return result.returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


async def check_docker_services_running() -> tuple[bool, str]:
    """Check if required Docker services are running."""
    # Get Redis password from environment
    import os

    redis_password = os.getenv("REDIS_PASSWORD")

    # Debug: Show what password we're using
    print("\n[DEBUG] check_docker_services_running:")
    print(f"  REDIS_PASSWORD from env: {'SET' if redis_password else 'NOT SET'}")
    print(f"  REDIS_URL from env: {os.getenv('REDIS_URL', 'NOT SET')}")

    # Check all required services
    # For HAProxy, we need a special check that connects without auth then sends AUTH
    haproxy_ok = await check_haproxy_redis_connection("localhost", 6380, redis_password)

    checks = {
        "Local Redis (6379)": await check_redis_connection("localhost", 6379, redis_password),
        "HAProxy Redis (6380)": haproxy_ok,
        "HAProxy Stats (8080)": bool(await check_haproxy_stats()),
        "Flower API (5555)": await check_flower_api(),
    }

    all_running = all(checks.values())

    if not all_running:
        failed = [name for name, status in checks.items() if not status]
        message = (
            f"Required services not running: {', '.join(failed)}. Run 'docker compose up -d' first."
        )
        return False, message

    return True, "All services running"


def skip_if_not_in_docker(reason: str | None = None) -> pytest.MarkDecorator:
    """Skip test if not running inside Docker container."""
    if reason is None:
        reason = "Test only valid when running inside Docker container"
    return pytest.mark.skipif(not is_running_in_docker(), reason=reason)


def skip_if_no_docker_daemon(reason: str | None = None) -> pytest.MarkDecorator:
    """Skip test if Docker daemon is not available."""
    if reason is None:
        reason = "Docker daemon not available"
    return pytest.mark.skipif(not check_docker_daemon(), reason=reason)
