"""Test browser tasks run correctly in Celery threads pool.

This test verifies that browser tasks execute without coroutine serialization errors
when using the threads pool with async_to_sync bridge.

NOTE: This test requires Docker services to be running:
    docker compose up -d
"""

import asyncio
import os
import time
from typing import Any

import pytest


def _is_running_in_docker() -> bool:
    """Check if we're running inside a Docker container."""
    # Check for .dockerenv file
    if os.path.exists("/.dockerenv"):
        return True
    # Check if we're in a container by looking at cgroup
    try:
        with open("/proc/1/cgroup") as f:
            return "docker" in f.read()
    except Exception:
        return False


# Configure Redis and Flower URLs based on environment
# Get the actual Redis password from environment
redis_password = os.environ.get(
    "REDIS_PASSWORD", "AcKiAAIjcDE1MDQ1NTAwMThkNzQ0N2E0OGRhYzAxZjQyZTQyOTUzN3AxMA"
)

if _is_running_in_docker():
    # Inside Docker: use service names
    redis_host = "haproxy-redis"
    flower_host = "flower"
else:
    # On host: use localhost
    redis_host = "localhost"
    flower_host = "localhost"

# Always use HAProxy endpoint on port 6380 with auth
broker = f"redis://default:{redis_password}@{redis_host}:6380/0"
os.environ["REDIS_URL"] = broker
os.environ["REDIS__URL"] = broker  # Settings class expects double underscore
os.environ["REDIS__ENABLED"] = "true"
os.environ["CELERY_BROKER_URL"] = broker  # Also set singular form
os.environ["CELERY_BROKER_URLS"] = broker

# Import after setting env vars
from swarm.celery_app import app  # noqa: E402
from swarm.tasks.browser import goto, screenshot  # noqa: E402
from tests.integration.utils import check_docker_services_running  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def verify_docker_services() -> None:
    """Verify Docker services are running before tests."""

    # Run the async check in a new event loop
    async def _check() -> tuple[bool, str]:
        return await check_docker_services_running()

    services_ok, message = asyncio.run(_check())
    if not services_ok:
        pytest.skip(message)


def _wait_for_browser_worker(timeout: float = 20.0) -> None:
    """Block until at least one browser worker is ready to accept tasks."""
    import requests

    deadline = time.time() + timeout
    flower_host = "flower" if _is_running_in_docker() else "localhost"
    flower_url = f"http://{flower_host}:5555"

    while time.time() < deadline:
        try:
            # Check Flower API for active workers
            response = requests.get(f"{flower_url}/api/workers", timeout=2.0)
            if response.status_code == 200:
                workers = response.json()
                # Check if any worker is handling browser queue
                for worker_name, worker_info in workers.items():
                    if isinstance(worker_info, dict):
                        active_queues = worker_info.get("active_queues", [])
                        if any(q.get("name") == "browser" for q in active_queues):
                            print(f"Found browser worker: {worker_name}")
                            # Give it a moment to fully initialize
                            time.sleep(2.0)
                            return
        except Exception as e:
            # Flower might not be ready yet, continue waiting
            print(f"Waiting for Flower/workers: {e}")
            pass
        time.sleep(1.0)
    raise RuntimeError("No browser worker became available within timeout")


@pytest.mark.integration
@pytest.mark.docker
def test_browser_goto_thread_pool() -> None:
    """Test that browser.goto task executes without coroutine serialization errors."""
    _wait_for_browser_worker()

    # Debug: Check app configuration
    print(f"Celery broker URL: {app.conf.broker_url}")
    print(f"Task routes: {app.conf.task_routes}")

    # Use the imported task function directly
    result = goto.delay(url="https://example.com")
    print(f"Task sent with ID: {result.id}")
    print(f"Task state before get: {result.state}")

    # Wait for result with longer timeout for first task
    res = result.get(timeout=30)  # Give more time for first task to initialize browser
    print(f"Task result: {res}")
    assert res["success"] is True
    assert res["url"] == "https://example.com"
    # task_id should be the celery task ID
    assert "task_id" in res
    assert res["task_id"] == result.id

    # Cleanup
    from swarm.tasks.browser import cleanup  # noqa: E402

    cleanup.delay(task_id=res["task_id"]).get(timeout=10)


@pytest.mark.integration
@pytest.mark.docker
def test_browser_screenshot_thread_pool() -> None:
    """Test that browser.screenshot task executes and returns base64 data."""
    _wait_for_browser_worker()
    # First navigate to a page
    goto_result = goto.delay(url="https://example.com")
    print(f"Goto task ID: {goto_result.id}")
    goto_res = goto_result.get(timeout=30)
    assert goto_res["success"] is True
    task_id = goto_res["task_id"]
    print(f"Using task_id for screenshot: {task_id}")

    from swarm.tasks.browser import cleanup  # noqa: E402

    try:
        # Then take a screenshot using the same browser session
        screenshot_res = screenshot.delay(task_id=task_id).get(timeout=30)
        assert screenshot_res["success"] is True
        assert "data" in screenshot_res
        # Should be base64 encoded
        assert isinstance(screenshot_res["data"], str)
        assert len(screenshot_res["data"]) > 100  # Should have actual image data
    finally:
        # Cleanup the browser engine
        cleanup.delay(task_id=task_id).get(timeout=10)


@pytest.mark.integration
@pytest.mark.docker
def test_browser_click_thread_pool() -> None:
    """Test that browser.click task executes without errors."""
    _wait_for_browser_worker()

    # Navigate first and get the task_id for session reuse
    goto_result = goto.delay(url="https://example.com")
    goto_res = goto_result.get(timeout=30)  # Increased timeout for first browser launch
    assert goto_res["success"] is True
    task_id = goto_res["task_id"]

    # Import tasks
    from swarm.tasks.browser import cleanup, click  # noqa: E402

    try:
        # Click on the "More information..." link that exists on example.com
        # Using text selector for reliability
        click_res = click.delay(task_id=task_id, selector='a:has-text("More information")').get(
            timeout=30
        )

        assert click_res["success"] is True
        assert click_res["selector"] == 'a:has-text("More information")'
    finally:
        # Always cleanup the browser engine to prevent resource leaks
        cleanup.delay(task_id=task_id).get(timeout=10)
