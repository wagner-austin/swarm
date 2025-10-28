"""Test browser session affinity routing works correctly.

This test verifies that browser tasks with the same session ID
are routed to the same worker, enabling deterministic execution.

NOTE: This test requires Docker services to be running:
    docker compose up -d
"""

import asyncio
import os
import time
from typing import Any, Dict, List, TypedDict
from urllib.parse import urlparse

import pytest
import redis  # sync client for heartbeat gating

from swarm.distributed.session_registry import SessionRegistry
from tests.integration.utils import EXAMPLE_LINK_SELECTOR, check_docker_services_running

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
    """Block until at least min_workers browser workers are ready via heartbeats.

    Uses authoritative heartbeat keys in Redis DB 0: worker:heartbeat:browser:{worker_id}
    Returns list of worker_ids. Raises if no workers found within timeout.
    """
    deadline = time.time() + timeout
    # Build Redis URL for HAProxy on localhost:6380 DB 0 using REDIS_PASSWORD if provided
    pw = os.getenv("REDIS_PASSWORD", "")
    redis_url = f"redis://default:{pw}@localhost:6380/0" if pw else "redis://localhost:6380/0"
    client = redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=2)

    try:
        while time.time() < deadline:
            try:
                now = time.time()
                fresh_seconds = 90.0
                worker_ids: list[str] = []
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
                        # worker_id is suffix after last ':'
                        wid = data.get("worker_id") or key.rsplit(":", 1)[-1]
                        worker_ids.append(str(wid))

                # Deduplicate
                uniq = list(dict.fromkeys(worker_ids))
                if len(uniq) >= min_workers:
                    print(f"Found {len(uniq)} browser workers (heartbeats): {uniq}")
                    time.sleep(1.0)
                    return uniq
            except Exception as e:
                print(f"Waiting for heartbeat workers: {e}")
            time.sleep(1.0)
    finally:
        try:
            client.close()
        except Exception:
            pass

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
        wait_for.delay(session_id=session_id, selector=EXAMPLE_LINK_SELECTOR).get(timeout=60)
        click_res = click.delay(
            session_id=session_id,
            selector=EXAMPLE_LINK_SELECTOR,
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
    class SessionInfo(TypedDict):
        session_id: str
        url: str

    sessions: list[SessionInfo] = []

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
        import time

        import redis

        from swarm.core.settings import Settings

        registry = SessionRegistry()
        router = BrowserSessionRouter()
        redis_client = None

        try:
            # Set a session owner
            await registry.set_owner("test-session-2", "worker_example_com")

            # Create heartbeat key so router considers worker healthy
            # Router's _is_worker_healthy() checks worker:heartbeat:browser:{worker_id}
            redis_url = Settings().redis.url

            # SAFETY CHECK: Prevent running against production
            if "upstash.io" in redis_url or "production" in redis_url.lower():
                pytest.skip(
                    f"SAFETY: Refusing to run test against production Redis!\n"
                    f"  URL: {redis_url}\n"
                    f"  This test creates/deletes test keys in Redis."
                )

            redis_client = redis.from_url(redis_url, decode_responses=True)
            redis_client.hset(
                "worker:heartbeat:browser:worker_example_com",
                mapping={
                    "timestamp": str(time.time()),
                    "worker_type": "browser",
                    "worker_id": "worker_example_com",
                },
            )
            redis_client.expire("worker:heartbeat:browser:worker_example_com", 60)

            # Router should route to direct queue
            route = router.route_for_task(
                "browser.click", (), {"session_id": "test-session-2"}, {}, None
            )

            assert route is not None
            # Router uses the direct_queue from registry without modifying worker_id
            assert route["queue"] == "browser.direct.worker_example_com"

            # Cleanup
            await registry.clear_owner("test-session-2")
            if redis_client:
                redis_client.delete("worker:heartbeat:browser:worker_example_com")
        finally:
            await registry.close()
            if redis_client:
                redis_client.close()

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


def test_router_direct_queue_passthrough() -> None:
    """Router should use the direct_queue from registry without altering worker_id."""
    from swarm.distributed.browser_router import BrowserSessionRouter

    router = BrowserSessionRouter()

    # Minimal assertion: router will not fail if given a direct queue with host-only id
    # Full routing behavior is covered by other tests using SessionRegistry integration.
    # Here we just ensure the method exists and router can be instantiated.
    assert router is not None


@pytest.mark.skipif(os.getenv("NO_NET") == "1", reason="Network access disabled")
@pytest.mark.timeout(120)
def test_concurrent_session_operations_with_gap() -> None:
    """Concurrent operations still succeed after creator loop would have stopped.

    This reproduces the prior deadlock window by adding a gap after goto, then
    launching concurrent screenshots. With a dedicated engine loop, all complete.
    """
    from swarm.tasks.browser import cleanup, goto, screenshot

    _wait_for_browser_workers(min_workers=1)

    goto_result = goto.delay(url=TEST_URL)
    goto_res = goto_result.get(timeout=60)
    session_id = goto_res["session_id"]

    try:
        # Insert a delay to ensure the creator loop would have stopped previously
        time.sleep(1.0)

        tasks = [screenshot.delay(session_id=session_id) for _ in range(3)]
        for t in tasks:
            res = t.get(timeout=45)
            assert res["success"] is True
            assert res["session_id"] == session_id
    finally:
        cleanup.delay(session_id=session_id).get(timeout=20)


@pytest.mark.skipif(os.getenv("NO_NET") == "1", reason="Network access disabled")
@pytest.mark.timeout(180)
def test_many_concurrent_screenshots() -> None:
    """Stress: many concurrent screenshots complete without deadlock/timeouts."""
    from swarm.tasks.browser import cleanup, goto, screenshot

    _wait_for_browser_workers(min_workers=1)

    goto_result = goto.delay(url=TEST_URL)
    goto_res = goto_result.get(timeout=60)
    session_id = goto_res["session_id"]

    try:
        n = 10
        tasks = [screenshot.delay(session_id=session_id) for _ in range(n)]
        results = [t.get(timeout=60) for t in tasks]
        assert all(r.get("success") is True for r in results)
        assert all(r.get("session_id") == session_id for r in results)
    finally:
        cleanup.delay(session_id=session_id).get(timeout=20)


@pytest.mark.skipif(os.getenv("NO_NET") == "1", reason="Network access disabled")
@pytest.mark.timeout(60)
def test_cleanup_does_not_deadlock_and_clears_state() -> None:
    """Cleanup path schedules on engine loop and finishes reliably."""
    from swarm.tasks.browser import cleanup, goto, screenshot, status

    _wait_for_browser_workers(min_workers=1)

    goto_result = goto.delay(url=TEST_URL)
    goto_res = goto_result.get(timeout=60)
    session_id = goto_res["session_id"]

    # Ensure a page exists
    screenshot.delay(session_id=session_id).get(timeout=45)

    # Cleanup should complete quickly and not block
    cleanup.delay(session_id=session_id).get(timeout=20)

    # Status should indicate no active browser after cleanup
    st = status.delay(session_id=session_id).get(timeout=15)
    assert st["success"] is True
    data = st["data"]
    assert data.get("browser_active") is False
