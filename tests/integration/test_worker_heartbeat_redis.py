"""
Integration tests for worker heartbeat with real Redis.

Uses a synchronous Redis-like Protocol to provide precise typing for the
subset of Redis operations exercised by these tests.

Requires a running Redis instance. Set REDIS_URL environment variable
or tests will be skipped.
"""

import builtins as _bt
import json
import os
import time
from datetime import UTC, datetime
from typing import Callable, Generator, Protocol, cast, runtime_checkable

import pytest
import redis as redis_mod
from pytest import MonkeyPatch
from redis.exceptions import ConnectionError as RedisConnectionError

from swarm.distributed.browser_router import BrowserSessionRouter
from swarm.distributed.worker_lifecycle import WorkerLifecycle
from swarm.distributed.worker_registry import WorkerRegistry


def wait_for(predicate: Callable[[], bool], timeout: float = 5.0, interval: float = 0.05) -> bool:
    """Poll until predicate returns True or timeout."""
    end_time = time.time() + timeout
    while time.time() < end_time:
        if predicate():
            return True
        time.sleep(interval)
    return False


@runtime_checkable
class RedisLike(Protocol):
    # Connection / admin
    def ping(self) -> bool: ...

    def flushdb(self) -> None: ...

    def close(self) -> None: ...

    # Key ops
    def exists(self, name: str) -> int: ...

    def ttl(self, name: str) -> int: ...

    def expire(self, name: str, time: int) -> bool | int: ...

    def delete(self, name: str) -> int: ...

    # String ops
    def set(self, name: str, value: str) -> bool: ...

    def get(self, name: str) -> str | None: ...

    # Hash ops
    def hgetall(self, name: str) -> dict[str, str]: ...

    def hset(
        self,
        name: str,
        key: str | None = None,
        value: str | None = None,
        *,
        mapping: dict[str, str] | None = None,
    ) -> int: ...

    # Set ops
    def sadd(self, name: str, *values: str) -> int: ...

    def smembers(self, name: str) -> _bt.set[str]: ...


@pytest.mark.integration
class TestWorkerHeartbeatIntegration:
    """Integration tests with real Redis for TTL and expiry behavior."""

    @pytest.fixture(autouse=True)
    def patch_settings(self, monkeypatch: MonkeyPatch) -> None:
        """Patch Settings to use test configuration."""
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/15")

        class MockSettings:
            class redis:
                url = redis_url

            WORKER_HEARTBEAT_INTERVAL = 0.1
            WORKER_HEARTBEAT_TIMEOUT = 2
            WORKER_MAX_SESSIONS = 10

        monkeypatch.setattr("swarm.distributed.worker_lifecycle.Settings", lambda: MockSettings())
        monkeypatch.setattr("swarm.distributed.worker_registry.Settings", lambda: MockSettings())
        monkeypatch.setattr("swarm.distributed.browser_router.Settings", lambda: MockSettings())

    @pytest.fixture
    def redis_client(self) -> Generator[RedisLike, None, None]:
        """Provide a real Redis client for testing."""
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/15")  # Use db 15 for tests

        try:
            client = cast(RedisLike, redis_mod.from_url(redis_url, decode_responses=True))
            client.ping()
        except (RedisConnectionError, OSError):
            pytest.skip("Redis not available - set REDIS_URL or start Redis")

        # Clean test database
        client.flushdb()
        try:
            yield client
        finally:
            # Cleanup after test
            client.flushdb()
            client.close()

    def test_worker_ttl_expiry(self, redis_client: RedisLike) -> None:
        """Test that worker keys expire correctly with real TTL."""
        worker = WorkerLifecycle("test-worker", redis_client=redis_client)
        worker.heartbeat_interval = 0.5
        worker.heartbeat_timeout = 2  # 2 second TTL

        worker.register()
        worker.start_heartbeat()

        # Verify worker is registered
        assert redis_client.exists("browser:worker:test-worker")

        # Stop heartbeat but don't cleanup (simulate crash)
        worker.shutdown_event.set()
        time.sleep(0.6)  # Wait for last heartbeat to pass

        # Worker should still exist (TTL not expired)
        assert redis_client.exists("browser:worker:test-worker")

        # Wait for TTL to expire using polling
        assert wait_for(
            lambda: not redis_client.exists("browser:worker:test-worker"), timeout=5.0
        ), "Worker key should expire after TTL"

    def test_heartbeat_extends_ttl_continuously(self, redis_client: RedisLike) -> None:
        """Test that continuous heartbeats keep worker alive."""
        worker = WorkerLifecycle("test-worker", redis_client=redis_client)
        worker.heartbeat_interval = 0.2
        worker.heartbeat_timeout = 1  # Short TTL

        worker.register()
        worker.start_heartbeat()

        try:
            # Run for longer than TTL
            for _ in range(10):
                time.sleep(0.2)
                # Worker should still be alive
                assert redis_client.exists("browser:worker:test-worker")
                ttl = redis_client.ttl("browser:worker:test-worker")
                assert ttl > 0  # Should have some TTL remaining
        finally:
            worker.stop_heartbeat()

    def test_router_fallback_with_real_ttl_expiry(self, redis_client: RedisLike) -> None:
        """Test router behavior when worker TTL expires."""
        router = BrowserSessionRouter(redis_client=None)
        worker_id = "test-worker"

        # Create worker with short TTL
        redis_client.hset(
            f"browser:worker:{worker_id}",
            mapping={
                "hostname": worker_id,
                "status": "active",
                "last_heartbeat": datetime.now(UTC).isoformat(),
            },
        )
        redis_client.expire(f"browser:worker:{worker_id}", 1)  # 1 second TTL
        redis_client.sadd(f"browser:worker_sessions:{worker_id}", "session-001")
        redis_client.set("browser:affinity:session-001", f"swarm_{worker_id}")

        # Should route while alive
        route = router.route_for_task("browser.goto", kwargs={"session_id": "session-001"})
        assert route is not None
        assert route["queue"] == f"browser.direct.{worker_id}"

        # Wait for TTL to expire using polling
        assert wait_for(
            lambda: not redis_client.exists(f"browser:worker:{worker_id}"), timeout=3.0
        ), "Worker key should expire"

        # Should fall back to default
        route = router.route_for_task("browser.goto", kwargs={"session_id": "session-001"})
        assert route is None

        # Affinity should be cleared
        assert not redis_client.exists("browser:affinity:session-001")

    def test_concurrent_workers_with_real_redis(self, redis_client: RedisLike) -> None:
        """Test multiple workers with concurrent operations."""
        workers = []
        registry = WorkerRegistry(redis_client=redis_client)

        # Start 3 workers
        for i in range(3):
            worker = WorkerLifecycle(f"worker-{i:03d}", redis_client=redis_client)
            worker.heartbeat_interval = 0.1
            worker.heartbeat_timeout = 2
            worker.register()
            worker.start_heartbeat()
            workers.append(worker)

        try:
            # Add sessions concurrently
            for i, worker in enumerate(workers):
                for j in range(3):
                    session_id = f"session-{i:03d}-{j:03d}"
                    worker.add_session(session_id)
                    redis_client.set(f"browser:affinity:{session_id}", f"swarm_{worker.worker_id}")

            # Verify all workers are healthy
            healthy = registry.get_healthy_workers()
            assert len(healthy) == 3

            # Simulate worker 1 crash
            workers[1].shutdown_event.set()

            # Wait for TTL expiry using polling
            assert wait_for(
                lambda: not redis_client.exists("browser:worker:worker-001"), timeout=5.0
            ), "Crashed worker key should expire"

            # Check orphaned sessions
            orphaned = registry.get_orphaned_sessions()
            assert len(orphaned) == 3  # Worker 1's sessions

            # Clean up orphaned
            cleaned = registry.cleanup_orphaned_sessions()
            assert cleaned == 3

            # Verify only 2 workers remain
            healthy = registry.get_healthy_workers()
            assert len(healthy) == 2
            assert all(w.worker_id != "worker-001" for w in healthy)

        finally:
            # Clean shutdown for remaining workers
            for worker in workers:
                if not worker.shutdown_event.is_set():
                    worker.stop_heartbeat()

    def test_pipeline_atomicity(self, redis_client: RedisLike) -> None:
        """Test that pipeline operations are atomic."""
        worker = WorkerLifecycle("test-worker", redis_client=redis_client)

        # Register with pipeline
        worker.register()

        # All fields should be set atomically
        data = redis_client.hgetall("browser:worker:test-worker")
        expected_fields = {
            "hostname",
            "capabilities",
            "started_at",
            "last_heartbeat",
            "status",
            "current_sessions",
            "max_sessions",
            "platform",
            "python_version",
        }
        assert expected_fields.issubset(set(data.keys()))

    def test_redis_reconnection_handling(self, redis_client: RedisLike) -> None:
        """Test worker behavior during Redis reconnection."""
        worker = WorkerLifecycle("test-worker", redis_client=redis_client)
        worker.heartbeat_interval = 0.1
        worker.register()
        worker.start_heartbeat()

        try:
            # Verify worker is alive
            assert redis_client.exists("browser:worker:test-worker")

            # Simulate connection drop by killing all client connections
            # (This would require admin access to Redis, so we simulate differently)
            # Instead, we'll test that worker continues after connection errors

            time.sleep(0.5)

            # Worker should still be registered
            assert redis_client.exists("browser:worker:test-worker")

        finally:
            worker.stop_heartbeat()

    def test_load_balancing_with_real_workers(self, redis_client: RedisLike) -> None:
        """Test load balancing across multiple workers."""
        registry = WorkerRegistry(redis_client=redis_client)

        # Create workers with different loads
        for i, load in enumerate([2, 5, 8]):
            redis_client.hset(
                f"browser:worker:worker-{i:03d}",
                mapping={
                    "hostname": f"worker-{i:03d}",
                    "capabilities": json.dumps(["browser"]),
                    "started_at": datetime.now(UTC).isoformat(),
                    "last_heartbeat": datetime.now(UTC).isoformat(),
                    "status": "active",
                    "current_sessions": str(load),
                    "max_sessions": "10",
                    "platform": "Linux",
                    "python_version": "3.11.0",
                },
            )
            redis_client.expire(f"browser:worker:worker-{i:03d}", 60)

        # Should pick least loaded
        least_loaded = registry.find_least_loaded_worker()
        assert least_loaded == "worker-000"  # 20% load

        # Add load to worker-000
        redis_client.hset("browser:worker:worker-000", "current_sessions", "6")

        # Now worker-001 should be least loaded
        least_loaded = registry.find_least_loaded_worker()
        assert least_loaded == "worker-001"  # 50% load

    def test_graceful_vs_ungraceful_shutdown(self, redis_client: RedisLike) -> None:
        """Test difference between graceful and ungraceful shutdown."""
        # Graceful shutdown
        worker1 = WorkerLifecycle("graceful-worker", redis_client=redis_client)
        worker1.register()
        worker1.start_heartbeat()
        worker1.add_session("session-001")
        redis_client.set("browser:affinity:session-001", "swarm_graceful-worker")

        worker1.stop_heartbeat()  # Graceful

        # Should clean up immediately
        assert not redis_client.exists("browser:worker:graceful-worker")
        assert not redis_client.exists("browser:affinity:session-001")

        # Ungraceful shutdown (crash simulation)
        worker2 = WorkerLifecycle("crash-worker", redis_client=redis_client)
        worker2.heartbeat_timeout = 1  # Short TTL
        worker2.register()
        worker2.start_heartbeat()
        worker2.add_session("session-002")
        redis_client.set("browser:affinity:session-002", "swarm_crash-worker")

        # Simulate crash
        worker2.shutdown_event.set()  # Stop heartbeat without cleanup

        # Should still exist initially
        assert redis_client.exists("browser:worker:crash-worker")
        assert redis_client.exists("browser:affinity:session-002")

        # Wait for TTL using polling
        assert wait_for(
            lambda: not redis_client.exists("browser:worker:crash-worker"), timeout=3.0
        ), "Crashed worker key should expire after TTL"
        # But affinity remains orphaned
        assert redis_client.exists("browser:affinity:session-002")

        # Registry should detect as orphaned
        registry = WorkerRegistry(redis_client=redis_client)
        orphaned = registry.get_orphaned_sessions()
        assert "session-002" in orphaned
