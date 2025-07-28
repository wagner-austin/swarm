"""
Test that all services properly use HAProxy for Redis connections.

This test verifies that services don't bypass HAProxy and connect directly to Redis.
"""

import asyncio
import subprocess
from typing import Any, cast

import pytest
import redis.asyncio as redis
from redis.exceptions import ConnectionError

from swarm.infra import async_close_redis
from tests.integration.utils import (
    check_docker_daemon,
    is_running_in_docker,
    skip_if_not_in_docker,
)


def get_redis_connections() -> dict[str, list[str]]:
    """Get active Redis connections from docker containers."""
    try:
        # Get all running containers
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True, check=True
        )
        containers = result.stdout.strip().split("\n")

        connections = {}
        for container in containers:
            if container and container != "haproxy-redis":
                # Check what the container is connected to
                try:
                    result = subprocess.run(
                        ["docker", "exec", container, "ss", "-tn", "state", "established"],
                        capture_output=True,
                        text=True,
                    )
                    # Parse connections looking for Redis ports
                    lines = result.stdout.strip().split("\n")
                    redis_conns = []
                    for line in lines:
                        if ":6379" in line or ":6380" in line:
                            redis_conns.append(line)
                    if redis_conns:
                        connections[container] = redis_conns
                except subprocess.CalledProcessError:
                    pass

        return connections
    except subprocess.CalledProcessError:
        return {}


@pytest.mark.docker
@pytest.mark.integration
def test_services_use_haproxy_not_direct_redis() -> None:
    """Verify all services connect to Redis through HAProxy (port 6380)."""
    if not check_docker_daemon():
        pytest.skip("Docker daemon not available. Please start Docker.")

    connections = get_redis_connections()

    if not connections:
        pytest.skip("No Docker containers running. Run 'docker compose up -d' first.")

    direct_redis_users = []
    for container, conns in connections.items():
        for conn in conns:
            # Check if connecting directly to Redis (6379) instead of HAProxy (6380)
            if ":6379" in conn and "haproxy" not in container.lower():
                direct_redis_users.append(f"{container}: {conn}")

    assert not direct_redis_users, (
        f"Services bypassing HAProxy and connecting directly to Redis:\n"
        f"{chr(10).join(direct_redis_users)}"
    )


@pytest.mark.docker
@pytest.mark.integration
@pytest.mark.asyncio
@skip_if_not_in_docker()
async def test_celery_broker_uses_haproxy() -> None:
    """Test that Celery broker URL points to HAProxy when running in Docker."""

    # Import here to avoid import errors if Celery not configured
    try:
        from swarm.celery_app import app

        broker_url = app.conf.broker_url
        if isinstance(broker_url, list):
            broker_urls = broker_url
        else:
            broker_urls = [broker_url]

        for url in broker_urls:
            # Parse URL to check host/port
            if "haproxy-redis:6380" in url or "localhost:6380" in url:
                continue  # Good, using HAProxy
            elif ":6379" in url and "haproxy" not in url:
                pytest.fail(f"Celery broker bypassing HAProxy: {url}")
    except ImportError:
        pytest.skip("Celery not installed")


@pytest.mark.docker
@pytest.mark.integration
@pytest.mark.asyncio
async def test_flower_connects_through_haproxy() -> None:
    """Verify Flower is configured to use HAProxy."""
    try:
        # Check Flower's environment in Docker
        result = subprocess.run(
            ["docker", "exec", "swarm-flower-1", "printenv", "CELERY_BROKER_URL"],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            broker_url = result.stdout.strip()
            assert "haproxy-redis:6380" in broker_url, (
                f"Flower not using HAProxy. Broker URL: {broker_url}"
            )
        else:
            pytest.skip("Flower container not running. Run 'docker compose up -d flower' first.")
    except subprocess.CalledProcessError:
        pytest.skip("Unable to check Flower configuration. Ensure Docker is running.")


@pytest.mark.docker
@pytest.mark.integration
@pytest.mark.asyncio
async def test_haproxy_health_check() -> None:
    """Test that HAProxy health checks are working."""
    # Check services first
    from tests.integration.utils import check_docker_services_running

    services_ok, message = await check_docker_services_running()
    if not services_ok:
        pytest.skip(message)

    # Connect through HAProxy
    haproxy_client = redis.from_url("redis://localhost:6380/0", decode_responses=True)

    # Connect directly to Redis
    direct_client = redis.from_url("redis://localhost:6379/0", decode_responses=True)

    try:
        # Both should work
        await haproxy_client.ping()
        await direct_client.ping()

        # Write through HAProxy
        test_key = "haproxy:health:test"
        test_value = "healthy"
        # Use cast to handle decode_responses type issues
        await cast(Any, haproxy_client).set(test_key, test_value)

        # Read directly from Redis - should see the value
        direct_value = await cast(Any, direct_client).get(test_key)
        assert direct_value == test_value, "HAProxy not proxying to Redis correctly"

        # Cleanup
        await haproxy_client.delete(test_key)

    finally:
        await async_close_redis(haproxy_client)
        await async_close_redis(direct_client)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
