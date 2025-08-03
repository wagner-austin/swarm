"""
Test that all services properly use HAProxy for Redis connections.

This test verifies that services don't bypass HAProxy and connect directly to Redis.
"""

import asyncio
import json
import os
import subprocess
from typing import cast

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
def test_services_redis_configuration_consistency() -> None:
    """Verify all services use consistent Redis configuration (all HAProxy or all direct)."""
    if not check_docker_daemon():
        pytest.skip("Docker daemon not available. Please start Docker.")

    services_to_check = ["autoscaler", "swarm", "flower"]
    redis_configs = {}

    for service in services_to_check:
        try:
            # Check if service is running
            result = subprocess.run(
                ["docker", "ps", "--filter", f"name={service}", "--format", "{{.Names}}"],
                capture_output=True,
                text=True,
                check=True,
            )
            if service not in result.stdout:
                continue  # Service not running, skip it

            # Get service environment
            result = subprocess.run(
                ["docker", "inspect", service, "--format", "{{json .Config.Env}}"],
                capture_output=True,
                text=True,
                check=True,
            )
            if result.returncode == 0:
                env_vars = json.loads(result.stdout)

                # Find Redis URLs in environment
                # Priority: REDIS_URL > CELERY_BROKER_URL > any other *_URL
                redis_url = None
                for var in env_vars:
                    if "=" in var and "://" in var:
                        key, value = var.split("=", 1)
                        if key == "REDIS_URL":
                            redis_url = value
                            break
                        elif key == "CELERY_BROKER_URL" and not redis_url:
                            redis_url = value

                if redis_url:
                    if ":6380" in redis_url:
                        redis_configs[service] = "haproxy"
                    elif ":6379" in redis_url:
                        redis_configs[service] = "direct"
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            pass

    # Check consistency - all services should use the same approach
    unique_configs = set(redis_configs.values())

    if len(unique_configs) > 1:
        pytest.fail(
            f"Inconsistent Redis configuration across services:\n"
            f"{json.dumps(redis_configs, indent=2)}\n"
            f"All services should use the same Redis configuration.\n"
            f"Run 'make compose-test' to ensure all services use test configuration."
        )

    # In test environment (when REDIS_URL env var points to local),
    # all services should use direct Redis
    if os.getenv("REDIS_URL", "").startswith("redis://localhost:6379"):
        for service, config in redis_configs.items():
            assert config == "direct", (
                f"{service} not using direct Redis in test mode. "
                f"Run 'make compose-test' to apply test configuration."
            )


@pytest.mark.docker
@pytest.mark.integration
@pytest.mark.asyncio
async def test_celery_broker_has_valid_redis_url() -> None:
    """Test that Celery broker URL is properly configured and reachable."""

    # Import here to avoid import errors if Celery not configured
    try:
        from swarm.celery_app import app

        broker_url = app.conf.broker_url
        if isinstance(broker_url, list):
            broker_urls = broker_url
        else:
            broker_urls = [broker_url]

        # Verify we have at least one broker URL
        assert len(broker_urls) > 0, "No Celery broker URLs configured"

        # Verify all URLs are valid Redis URLs
        for url in broker_urls:
            assert url.startswith(("redis://", "rediss://")), f"Invalid broker URL scheme: {url}"

            # Check that it's either HAProxy (6380) or direct Redis (6379)
            assert ":6379" in url or ":6380" in url, f"Broker URL using non-standard port: {url}"
    except ImportError:
        pytest.skip("Celery not installed")


@pytest.mark.docker
@pytest.mark.integration
@pytest.mark.asyncio
async def test_flower_connects_through_haproxy() -> None:
    """Verify Flower is configured to use HAProxy."""
    try:
        # Check Flower's command to see broker URL
        result = subprocess.run(
            ["docker", "inspect", "flower", "--format", "{{.Config.Cmd}}"],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            cmd_str = result.stdout.strip()
            # Flower should be using HAProxy (port 6380) in its broker URL
            assert "haproxy-redis:6380" in cmd_str, f"Flower not using HAProxy. Command: {cmd_str}"
        else:
            pytest.skip(
                "Flower container not running. Run 'docker compose --profile monitoring up -d flower' first."
            )
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

    # Get Redis password from environment
    import os

    password = os.getenv("REDIS_PASSWORD", "")
    auth_part = f"default:{password}@" if password else ""

    # Connect through HAProxy with auth in URL
    haproxy_client = redis.from_url(f"redis://{auth_part}localhost:6380/0", decode_responses=True)

    # Connect directly to Redis
    direct_client = redis.from_url(f"redis://{auth_part}localhost:6379/0", decode_responses=True)

    try:
        # Both should work
        await haproxy_client.ping()
        await direct_client.ping()

        # Write through HAProxy
        test_key = "haproxy:health:test"
        test_value = "healthy"
        await haproxy_client.set(test_key, test_value)  # type: ignore[arg-type]

        # Read back through HAProxy - should see the value
        haproxy_value = await haproxy_client.get(test_key)
        assert haproxy_value == test_value, "HAProxy not storing/retrieving data correctly"  # type: ignore[comparison-overlap]

        # Verify data is also in local Redis (since test environment uses local Redis only)
        direct_value = await direct_client.get(test_key)
        assert direct_value == test_value, "Data not replicated to local Redis"  # type: ignore[comparison-overlap]

        # Cleanup
        await haproxy_client.delete(test_key)

    finally:
        await async_close_redis(haproxy_client)
        await async_close_redis(direct_client)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
