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
import redis
from celery.app.base import Celery

from tests.integration.utils import EXAMPLE_LINK_SELECTOR, check_docker_services_running


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
    """Block until at least one browser worker is ready via heartbeat in DB 0."""
    deadline = time.time() + timeout
    pw = os.getenv("REDIS_PASSWORD", "")
    redis_url = f"redis://default:{pw}@localhost:6380/0" if pw else "redis://localhost:6380/0"
    client = redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=2)

    try:
        while time.time() < deadline:
            try:
                now = time.time()
                fresh_seconds = 90.0
                for key in client.scan_iter(match="worker:heartbeat:browser:*"):
                    data = client.hgetall(key)
                    ts_str = data.get("timestamp")
                    if not ts_str:
                        continue
                    try:
                        ts = float(ts_str)
                    except Exception:
                        continue
                    if (now - ts) <= fresh_seconds:
                        wid = data.get("worker_id") or key.rsplit(":", 1)[-1]
                        print(f"Found browser worker (heartbeat): {wid}")
                        time.sleep(1.0)
                        return
            except Exception as e:
                print(f"Waiting for heartbeat worker: {e}")
            time.sleep(1.0)
    finally:
        try:
            client.close()
        except Exception:
            pass
    raise RuntimeError("No browser worker became available within timeout")


@pytest.mark.integration
@pytest.mark.docker
def test_browser_goto_thread_pool() -> None:
    """Test that browser.goto task executes without coroutine serialization errors."""
    # Import tasks after app is configured to ensure they use the test app
    from swarm.tasks.browser import cleanup, goto  # noqa: E402

    _wait_for_browser_worker()

    # Debug: Check app configuration
    from swarm.celery_app import app as celery_app

    print(f"Celery broker URL: {celery_app.conf.broker_url}")
    print(f"Celery result backend: {celery_app.conf.result_backend}")
    print(f"Task routes: {celery_app.conf.task_routes}")

    # Use the imported task function directly
    result = goto.delay(url="https://example.com")
    print(f"Task sent with ID: {result.id}")
    print(f"Task state before get: {result.state}")

    # Wait for result with longer timeout for first task
    res = result.get(timeout=30)  # Give more time for first task to initialize browser
    print(f"Task result: {res}")
    assert res["success"] is True
    assert res["url"] == "https://example.com"
    # session_id should default to the Celery task ID when not provided
    assert "session_id" in res
    assert res["session_id"] == result.id

    # Cleanup
    cleanup.delay(session_id=res["session_id"]).get(timeout=10)


@pytest.mark.integration
@pytest.mark.docker
def test_browser_screenshot_thread_pool() -> None:
    """Test that browser.screenshot task executes and returns base64 data."""
    # Import tasks after app is configured
    from swarm.tasks.browser import cleanup, goto, screenshot  # noqa: E402

    _wait_for_browser_worker()
    # First navigate to a page
    goto_result = goto.delay(url="https://example.com")
    print(f"Goto task ID: {goto_result.id}")
    goto_res = goto_result.get(timeout=30)
    assert goto_res["success"] is True
    session_id = goto_res["session_id"]
    print(f"Using session_id for screenshot: {session_id}")

    try:
        # Then take a screenshot using the same browser session
        screenshot_res = screenshot.delay(session_id=session_id).get(timeout=30)
        assert screenshot_res["success"] is True
        assert "data" in screenshot_res
        # Should be base64 encoded
        assert isinstance(screenshot_res["data"], str)
        assert len(screenshot_res["data"]) > 100  # Should have actual image data
    finally:
        # Cleanup the browser engine
        cleanup.delay(session_id=session_id).get(timeout=10)


@pytest.mark.integration
@pytest.mark.docker
def test_browser_click_thread_pool() -> None:
    """Test that browser.click task executes without errors."""
    # Import tasks after app is configured
    from swarm.tasks.browser import cleanup, click, goto, wait_for  # noqa: E402

    _wait_for_browser_worker()

    # Navigate first and get the session_id for session reuse
    goto_result = goto.delay(url="https://example.com")
    goto_res = goto_result.get(timeout=30)  # Increased timeout for first browser launch
    assert goto_res["success"] is True
    session_id = goto_res["session_id"]

    try:
        # Click on the "More information..." link that exists on example.com
        # Using text selector for reliability
        # Wait for the element to be visible to reduce CI timing flakes
        wait_for.delay(session_id=session_id, selector=EXAMPLE_LINK_SELECTOR).get(timeout=60)
        click_res = click.delay(
            session_id=session_id,
            selector=EXAMPLE_LINK_SELECTOR,
            no_wait_after=True,
        ).get(timeout=30)

        assert click_res["success"] is True
        assert click_res["selector"] == EXAMPLE_LINK_SELECTOR
    finally:
        # Always cleanup the browser engine to prevent resource leaks
        cleanup.delay(session_id=session_id).get(timeout=10)
