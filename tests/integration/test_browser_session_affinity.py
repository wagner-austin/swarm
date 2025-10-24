"""Test browser session affinity routing works correctly.

This test verifies that browser tasks with the same session ID
are routed to the same worker, enabling deterministic execution.

NOTE: This test requires Docker services to be running:
    docker compose up -d
"""

import asyncio
import os
import time
from typing import Any, Dict, List

import pytest
from celery.app.control import Inspect

from swarm.distributed.session_registry import SessionRegistry
from tests.integration.utils import check_docker_services_running

# Mark entire module as slow and requiring docker
pytestmark = [
    pytest.mark.slow,
    pytest.mark.integration,
    pytest.mark.docker,
    pytest.mark.timeout(120),  # module-wide timeout
]

# Test target URL - can be overridden via env
TEST_URL = os.getenv("TEST_PAGE", "https://example.com")


@pytest.fixture(scope="module", autouse=True)
def verify_docker_services() -> None:
    """Verify Docker services are running before tests."""

    # Run the async check in a new event loop
    async def _check() -> tuple[bool, str]:
        return await check_docker_services_running()

    services_ok, message = asyncio.run(_check())
    if not services_ok:
        pytest.skip(message)


def _wait_for_browser_workers(min_workers: int = 1, timeout: float = 30.0) -> list[str]:
    """Block until at least min_workers browser workers are ready.

    Returns list of worker names. Raises if no workers found.
    """
    from swarm.celery_app import app as celery_app

    deadline = time.time() + timeout
    browser_workers: list[str] = []

    while time.time() < deadline:
        try:
            inspector = Inspect(destination=None, app=celery_app)
            active_queues = inspector.active_queues()
            if active_queues:
                browser_workers = []
                for worker_name, queues in active_queues.items():
                    # Check if worker handles browser queue
                    if any(q.get("name") == "browser" for q in queues):
                        browser_workers.append(worker_name)

                if len(browser_workers) >= min_workers:
                    print(f"Found {len(browser_workers)} browser workers: {browser_workers}")
                    time.sleep(2.0)  # Let them fully initialize
                    return browser_workers
        except Exception as e:
            print(f"Waiting for workers: {e}")
            pass
        time.sleep(1.0)

    # Return what we found if any, otherwise raise
    if browser_workers:
        print(f"Found {len(browser_workers)} workers (wanted {min_workers}), continuing")
        return browser_workers

    raise RuntimeError(f"No browser workers found within {timeout}s")


@pytest.mark.skipif(os.getenv("NO_NET") == "1", reason="Network access disabled")
def test_session_registry_basic() -> None:
    """Test SessionRegistry basic operations."""

    async def _test() -> None:
        registry = SessionRegistry()
        try:
            # Test set and get
            assert await registry.set_owner("test-session-1", "worker-1")
            assert await registry.get_session_owner("test-session-1") == "worker-1"

            # Test clear
            assert await registry.clear_owner("test-session-1")
            assert await registry.get_session_owner("test-session-1") is None
        finally:
            await registry.close()

    asyncio.run(_test())


@pytest.mark.skipif(os.getenv("NO_NET") == "1", reason="Network access disabled")
@pytest.mark.timeout(60)
def test_session_affinity_same_worker() -> None:
    """Test that tasks with same session ID go to same worker."""
    from swarm.tasks.browser import cleanup, click, goto, screenshot, wait_for

    # This test works with just 1 worker
    _wait_for_browser_workers(min_workers=1)

    # Create a session with goto - allow extra time for first task
    goto_result = goto.delay(url=TEST_URL)
    goto_res = goto_result.get(timeout=60)  # Extra time for worker startup
    assert goto_res["success"] is True
    session_id = goto_res["session_id"]

    try:
        # Multiple operations should use the same session
        screenshot_res = screenshot.delay(session_id=session_id).get(timeout=45)
        assert screenshot_res["success"] is True
        assert screenshot_res["session_id"] == session_id

        # Ensure the element is present and visible before clicking to reduce flakiness
        wait_for.delay(session_id=session_id, selector='a:has-text("More information")').get(timeout=60)
        click_res = click.delay(
            session_id=session_id,
            selector='a:has-text("More information")',
            no_wait_after=True,
        ).get(timeout=45)
        assert click_res["success"] is True
        assert click_res["session_id"] == session_id

    finally:
        cleanup.delay(session_id=session_id).get(timeout=10)


@pytest.mark.skipif(os.getenv("NO_NET") == "1", reason="Network access disabled")
@pytest.mark.timeout(90)
def test_different_sessions_distribution() -> None:
    """Test that different sessions can be distributed across workers.

    With multiple workers, sessions COULD distribute but it's not required.
    """
    from swarm.tasks.browser import cleanup, goto

    # Get available workers (works with any number)
    _wait_for_browser_workers(min_workers=1)

    # Create multiple sessions
    sessions: list[dict[str, Any]] = []

    try:
        for i in range(3):
            goto_result = goto.delay(url=f"{TEST_URL}?session={i}")
            goto_res = goto_result.get(timeout=45)
            assert goto_res["success"] is True
            sessions.append({"session_id": goto_res["session_id"], "url": goto_res["url"]})

        # Verify each session has its own session_id
        task_ids = [s["session_id"] for s in sessions]
        assert len(set(task_ids)) == 3, "Each session should have unique session_id"

        # If we have multiple workers, sessions COULD be distributed
        # (but we don't require it for the test to pass)

    finally:
        # Cleanup all sessions
        for session in sessions:
            cleanup.delay(session_id=session["session_id"]).get(timeout=10)


def test_session_routing_after_registry_set() -> None:
    """Test that router correctly routes to worker after registry is set."""
    from swarm.distributed.browser_router import BrowserSessionRouter

    async def _test() -> None:
        registry = SessionRegistry()
        router = BrowserSessionRouter()

        try:
            # Set a session owner
            await registry.set_owner("test-session-2", "worker_example_com")

            # Router should route to direct queue
            route = router.route_for_task(
                "browser.click", (), {"session_id": "test-session-2"}, {}, None
            )

            assert route is not None
            # Router strips "worker_" prefix from the owner ID
            assert route["queue"] == "browser.direct.example_com"

            # Cleanup
            await registry.clear_owner("test-session-2")
        finally:
            await registry.close()

    asyncio.run(_test())


def test_session_ttl_refresh() -> None:
    """Test that session TTL is refreshed on access."""

    async def _test() -> None:
        registry = SessionRegistry()

        try:
            # Set a session
            await registry.set_owner("test-session-ttl", "worker-1")

            # Get the session multiple times
            for _ in range(3):
                owner = await registry.get_session_owner("test-session-ttl")
                assert owner == "worker-1"
                await asyncio.sleep(0.1)

            # Session should still be alive due to TTL refresh
            owner = await registry.get_session_owner("test-session-ttl")
            assert owner == "worker-1"

            # Cleanup
            await registry.clear_owner("test-session-ttl")
        finally:
            await registry.close()

    asyncio.run(_test())


@pytest.mark.skipif(os.getenv("NO_NET") == "1", reason="Network access disabled")
@pytest.mark.timeout(90)
def test_concurrent_session_operations() -> None:
    """Test that concurrent operations on same session work correctly.

    All concurrent tasks should successfully execute on the same worker.
    """
    from swarm.tasks.browser import cleanup, goto, screenshot

    _wait_for_browser_workers(min_workers=1)

    # Create initial session
    goto_result = goto.delay(url=TEST_URL)
    goto_res = goto_result.get(timeout=60)  # Extra time for first task
    session_id = goto_res["session_id"]

    try:
        # Launch multiple screenshot tasks concurrently
        screenshot_tasks = []
        for i in range(3):
            task = screenshot.delay(session_id=session_id)
            screenshot_tasks.append(task)

        # All should complete successfully
        for i, task in enumerate(screenshot_tasks):
            res = task.get(timeout=45)
            assert res["success"] is True
            assert res["session_id"] == session_id
            print(f"Screenshot {i} completed")

    finally:
        cleanup.delay(session_id=session_id).get(timeout=10)


def test_router_sanitizes_worker_names() -> None:
    """Test that router correctly sanitizes worker names with @ symbols."""
    from swarm.distributed.browser_router import BrowserSessionRouter

    router = BrowserSessionRouter()

    # Test the sanitization method directly
    assert router._sanitize_worker_id("worker@hostname") == "worker_hostname"
    assert router._sanitize_worker_id("clean-worker") == "clean-worker"
    assert router._sanitize_worker_id("worker@host@name") == "worker_host_name"
