"""
Integration tests for session management modules:
- swarm.distributed.session_registry
- swarm.distributed.browser_router
- swarm.distributed.session_lifecycle

These tests require a local Redis on 6379 and use DB 15 to avoid
conflicts with production DB 0. They do not require running workers.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Generator

import pytest
import redis as redis_mod

from swarm.distributed.browser_router import BrowserSessionRouter
from swarm.distributed.session_lifecycle import SessionLifecycleManager
from swarm.distributed.session_registry import SessionRegistry
from swarm.infra.redis_keys import affinity_key as ak, heartbeat_key as hb

pytestmark = [
    pytest.mark.integration,
    pytest.mark.timeout(120),
]


@pytest.fixture
def redis_client() -> Generator[redis_mod.Redis[str], None, None]:
    """Provide a real Redis client on DB 15, skipping if unsafe or unavailable."""
    password = os.getenv("REDIS_PASSWORD")
    if password:
        redis_url = f"redis://default:{password}@localhost:6379/15"
    else:
        redis_url = "redis://localhost:6379/15"

    # SAFETY: never run against production endpoints or DB 0
    if (
        "upstash.io" in redis_url
        or ":6380" in redis_url
        or redis_url.rstrip("/").endswith("/0")
        or "production" in redis_url.lower()
    ):
        pytest.skip(
            f"SAFETY: refusing to use production Redis for tests: {redis_url}.\n"
            f"Use localhost:6379 DB 15."
        )

    try:
        client: redis_mod.Redis[str] = redis_mod.from_url(redis_url, decode_responses=True)
        client.ping()
    except Exception:
        pytest.skip("Redis not available on localhost:6379 (DB 15)")

    client.flushdb()
    try:
        yield client
    finally:
        try:
            client.flushdb()
        finally:
            client.close()


@pytest.fixture(autouse=True)
def patch_settings_for_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch Settings in modules under test to use DB 15 on localhost:6379.

    Ensures SessionRegistry and BrowserSessionRouter create clients against
    the isolated test database rather than production HAProxy/DB0.
    """
    password = os.getenv("REDIS_PASSWORD")
    if password:
        redis_url = f"redis://default:{password}@localhost:6379/15"
    else:
        redis_url = "redis://localhost:6379/15"

    class MockSettings:
        class redis:  # type: ignore[override]
            url = redis_url

        class sessions:  # minimal surface used by lifecycle
            ttl_seconds = 3600
            cleanup_interval_seconds = 0.5

    # Ensure all modules under test use the isolated local Redis DB 15
    monkeypatch.setattr("swarm.distributed.session_registry.Settings", lambda: MockSettings())
    monkeypatch.setattr("swarm.distributed.browser_router.Settings", lambda: MockSettings())
    # SessionLifecycleManager resolves Settings from swarm.core at runtime
    monkeypatch.setattr("swarm.core.settings.Settings", lambda: MockSettings())
    monkeypatch.setattr("swarm.distributed.worker_lifecycle.Settings", lambda: MockSettings())


def test_registry_finds_orphans(redis_client: redis_mod.Redis[str]) -> None:
    """SessionRegistry.find_orphaned_sessions_sync detects sessions for dead workers."""
    # Healthy worker A
    redis_client.hset(
        hb("worker-A"),
        mapping={"timestamp": str(time.time()), "worker_type": "browser", "worker_id": "worker-A"},
    )
    redis_client.expire(hb("worker-A"), 30)

    # Session for healthy worker A
    redis_client.hset(
        ak("sess-A1"),
        mapping={
            "worker_id": "worker-A",
            "direct_queue": "browser.direct.worker-A",
            "timestamp": str(time.time()),
        },
    )

    # Session for dead worker B (no heartbeat)
    redis_client.hset(
        ak("sess-B1"),
        mapping={
            "worker_id": "worker-B",
            "direct_queue": "browser.direct.worker-B",
            "timestamp": str(time.time()),
        },
    )

    out = SessionRegistry.find_orphaned_sessions_sync(redis_client)
    assert "sess-B1" in out
    assert "sess-A1" not in out


def test_router_cleanup_routes_to_direct_when_healthy(
    redis_client: redis_mod.Redis[str],
) -> None:
    """Router special-case: browser.cleanup routes to owner's direct queue if healthy."""
    # Owner mapping
    redis_client.hset(
        ak("sess-clean"),
        mapping={
            "worker_id": "worker-clean",
            "direct_queue": "browser.direct.worker-clean",
            "timestamp": str(time.time()),
        },
    )
    # Heartbeat alive
    redis_client.hset(
        hb("worker-clean"),
        mapping={
            "timestamp": str(time.time()),
            "worker_type": "browser",
            "worker_id": "worker-clean",
        },
    )
    redis_client.expire(hb("worker-clean"), 30)

    router = BrowserSessionRouter(redis_client=redis_client)
    route = router.route_for_task("browser.cleanup", (), {"session_id": "sess-clean"}, {}, None)
    assert route is not None
    assert route["queue"] == "browser.direct.worker-clean"
    assert route["exchange"] == "browser.direct.worker-clean"
    assert route["routing_key"] == "browser.direct.worker-clean"


def test_router_unhealthy_clears_affinity_for_non_cleanup(
    redis_client: redis_mod.Redis[str],
) -> None:
    """When worker unhealthy, router clears affinity and falls back to default routing (None)."""
    # Owner mapping exists, but no heartbeat
    redis_client.hset(
        ak("sess-dead"),
        mapping={
            "worker_id": "worker-dead",
            "direct_queue": "browser.direct.worker-dead",
            "timestamp": str(time.time()),
        },
    )

    router = BrowserSessionRouter(redis_client=redis_client)
    res = router.route_for_task("browser.screenshot", (), {"session_id": "sess-dead"}, {}, None)
    # Default routing (None) and affinity cleared
    assert res is None
    assert redis_client.exists(ak("sess-dead")) == 0


def test_router_cleanup_falls_back_when_unhealthy(redis_client: redis_mod.Redis[str]) -> None:
    """Cleanup task falls back to base queue when owner is unhealthy (does not delete affinity)."""
    redis_client.hset(
        ak("sess-clean-dead"),
        mapping={
            "worker_id": "worker-clean-dead",
            "direct_queue": "browser.direct.worker-clean-dead",
            "timestamp": str(time.time()),
        },
    )
    router = BrowserSessionRouter(redis_client=redis_client)
    route = router.route_for_task(
        "browser.cleanup", (), {"session_id": "sess-clean-dead"}, {}, None
    )
    assert route is not None
    assert route["queue"] == "browser"
    # Affinity remains (cleanup fallback doesn't delete)
    assert redis_client.exists(ak("sess-clean-dead")) == 1


def test_lifecycle_ttl_cleanup_clears_registry(redis_client: redis_mod.Redis[str]) -> None:
    """Lifecycle manager expires sessions and clears registry affinity on cleanup."""

    async def _run() -> None:
        # Pre-create registry owner to verify clearing on cleanup
        reg = SessionRegistry()
        await reg.set_owner("sess-L1", "worker-L1")
        await reg.close()

        mgr = SessionLifecycleManager(cleanup_interval=0.1)
        mgr.start()
        try:
            # Register with short TTL for quick expiry
            await mgr.register_session("sess-L1", "worker-L1", ttl_seconds=0.5)

            # Initially active
            snap1 = await mgr.get_metrics_snapshot()
            assert snap1["total_active"] >= 1

            # Wait for TTL expiry and cleanup loop to run
            deadline = time.time() + 5.0
            while time.time() < deadline:
                snap = await mgr.get_metrics_snapshot()
                if snap["total_active"] == 0:
                    break
                await asyncio.sleep(0.05)
            else:
                pytest.fail("Lifecycle did not expire session within timeout")

            # Registry affinity should be cleared by cleanup path
            reg2 = SessionRegistry()
            owner = await reg2.get_session_owner("sess-L1")
            await reg2.close()
            assert owner is None
        finally:
            mgr.stop()

    asyncio.run(_run())


def test_lifecycle_unregister_clears_and_updates_metrics(
    redis_client: redis_mod.Redis[str],
) -> None:
    """Explicit unregister removes session promptly and metrics reflect the change."""

    async def _run() -> None:
        # Create an affinity to be cleared on unregister
        reg = SessionRegistry()
        await reg.set_owner("sess-U1", "worker-U1")
        await reg.close()

        mgr = SessionLifecycleManager(cleanup_interval=0.1)
        mgr.start()
        try:
            await mgr.register_session("sess-U1", "worker-U1", ttl_seconds=10)
            snap1 = await mgr.get_metrics_snapshot()
            assert snap1["total_active"] >= 1

            await mgr.unregister_session("sess-U1")
            # Should be gone immediately
            snap2 = await mgr.get_metrics_snapshot()
            assert snap2["total_active"] == 0

            # Registry should be cleared
            reg2 = SessionRegistry()
            owner = await reg2.get_session_owner("sess-U1")
            await reg2.close()
            assert owner is None
        finally:
            mgr.stop()

    asyncio.run(_run())
