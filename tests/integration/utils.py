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
    except Exception:
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
    except Exception:
        pass

    return stats


async def check_flower_api(host: str = "localhost", port: int = 5555) -> bool:
    """Check if Flower API is responsive."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://{host}:{port}/api/workers") as resp:
                if resp.status == 200:
                    await resp.json()
                    return True
    except Exception:
        pass

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
    # Check all required services
    checks = {
        "Local Redis (6379)": await check_redis_connection("localhost", 6379),
        "HAProxy Redis (6380)": await check_redis_connection("localhost", 6380),
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
