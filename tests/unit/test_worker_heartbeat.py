"""
Unit tests for worker heartbeat and lifecycle management.

Tests use a synchronous Redis-like Protocol to provide precise typing
for the subset of Redis operations exercised by the tests.
"""

import builtins as _bt
import json
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from types import TracebackType
from typing import Any, Callable, Generator, Literal, Protocol, cast, runtime_checkable

import pytest
from fakeredis import FakeRedis
from pytest import MonkeyPatch
from redis.exceptions import ConnectionError as RedisConnectionError

from swarm.distributed.worker_lifecycle import WorkerLifecycle
from swarm.distributed.worker_registry import WorkerRegistry


def wait_for(condition: Callable[[], bool], timeout: float = 2.0, interval: float = 0.02) -> bool:
    """Wait for a condition to become true."""
    end_time = time.time() + timeout
    while time.time() < end_time:
        if condition():
            return True
        time.sleep(interval)
    return False


@contextmanager
def running_heartbeat(worker: WorkerLifecycle) -> Generator[None, None, None]:
    """Context manager for safe heartbeat lifecycle."""
    worker.start_heartbeat()
    try:
        yield
    finally:
        worker.stop_heartbeat()


class MockSettings:
    """Mock Settings for test isolation."""

    class redis:
        url = "redis://localhost:6379/0"

    WORKER_HEARTBEAT_INTERVAL = 0.1
    WORKER_HEARTBEAT_TIMEOUT = 2
    WORKER_MAX_SESSIONS = 10


@runtime_checkable
class _PipelineLike(Protocol):
    def __enter__(self) -> "_PipelineLike": ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool: ...

    def hset(
        self,
        name: str,
        key: str | None = None,
        value: str | None = None,
        *,
        mapping: dict[str, str] | None = None,
    ) -> "_PipelineLike": ...

    def expire(self, name: str, time: int) -> "_PipelineLike": ...

    def execute(self) -> list[Any]: ...


@runtime_checkable
class RedisLike(Protocol):
    """Synchronous subset of Redis operations used by tests."""

    # Hash operations
    def hgetall(self, name: str) -> dict[str, str]: ...

    def hget(self, name: str, key: str) -> str | None: ...

    def hset(
        self,
        name: str,
        key: str | None = None,
        value: str | None = None,
        *,
        mapping: dict[str, str] | None = None,
    ) -> int: ...

    # Key operations
    def exists(self, name: str) -> int: ...

    def ttl(self, name: str) -> int: ...

    def expire(self, name: str, time: int) -> bool | int: ...

    def delete(self, name: str) -> int: ...

    # String operations (legacy usage removed)

    # Set operations
    def smembers(self, name: str) -> _bt.set[str]: ...

    def sadd(self, name: str, *values: str) -> int: ...

    # Pipelining
    def pipeline(self) -> _PipelineLike: ...


class TestWorkerLifecycle:
    """Test worker lifecycle management with mocked Redis."""

    @pytest.fixture(autouse=True)
    def mock_settings(self, monkeypatch: MonkeyPatch) -> None:
        """Mock Settings to isolate tests from environment."""
        monkeypatch.setattr("swarm.distributed.worker_lifecycle.Settings", lambda: MockSettings())

    @pytest.fixture
    def redis_client(self) -> RedisLike:
        """Provide a fake Redis client for testing."""
        return cast(RedisLike, FakeRedis(decode_responses=True))

    @pytest.fixture
    def worker_lifecycle(self, redis_client: RedisLike) -> WorkerLifecycle:
        """Create a worker lifecycle instance with test Redis."""
        return WorkerLifecycle("test-worker-001", redis_client=cast(Any, redis_client))

    def test_worker_registration(
        self, worker_lifecycle: WorkerLifecycle, redis_client: RedisLike
    ) -> None:
        """Test that worker registration creates proper Redis keys."""
        worker_lifecycle.register()

        # Check worker key exists
        worker_key = "browser:worker:test-worker-001"
        assert redis_client.exists(worker_key)

        # Verify worker data
        worker_data = redis_client.hgetall(worker_key)
        assert worker_data["hostname"] == "test-worker-001"
        assert worker_data["status"] == "active"
        assert worker_data["current_sessions"] == "0"
        assert json.loads(worker_data["capabilities"]) == worker_lifecycle.capabilities

        # Check TTL is set
        ttl = redis_client.ttl(worker_key)
        assert ttl > 0
        assert ttl <= worker_lifecycle.heartbeat_timeout

    def test_heartbeat_updates_timestamp(
        self, worker_lifecycle: WorkerLifecycle, redis_client: RedisLike
    ) -> None:
        """Test that heartbeat thread updates last_heartbeat timestamp."""
        worker_lifecycle.heartbeat_interval = 0.05
        worker_lifecycle.register()

        initial_heartbeat = redis_client.hget("browser:worker:test-worker-001", "last_heartbeat")

        with running_heartbeat(worker_lifecycle):
            # Wait for heartbeat update
            def heartbeat_changed() -> bool:
                current = redis_client.hget("browser:worker:test-worker-001", "last_heartbeat")
                return current != initial_heartbeat

            assert wait_for(heartbeat_changed, timeout=1.0)

    def test_session_management(
        self, worker_lifecycle: WorkerLifecycle, redis_client: RedisLike
    ) -> None:
        """Test adding and removing sessions from worker."""
        worker_lifecycle.register()

        # Add sessions
        worker_lifecycle.add_session("session-001")
        worker_lifecycle.add_session("session-002")

        sessions_key = "browser:worker_sessions:test-worker-001"
        sessions = redis_client.smembers(sessions_key)
        assert "session-001" in sessions
        assert "session-002" in sessions

        # Remove a session
        worker_lifecycle.remove_session("session-001")
        sessions = redis_client.smembers(sessions_key)
        assert "session-001" not in sessions
        assert "session-002" in sessions

    def test_graceful_shutdown_clears_sessions(
        self, worker_lifecycle: WorkerLifecycle, redis_client: RedisLike
    ) -> None:
        """Test that stopping heartbeat clears session ownership."""
        worker_lifecycle.register()

        with running_heartbeat(worker_lifecycle):
            # Add sessions with proper ownership format (contract hash)
            worker_lifecycle.add_session("session-001")
            worker_lifecycle.add_session("session-002")
            now = time.time()
            redis_client.hset(
                "browser:affinity:session-001",
                mapping={
                    "worker_id": "test-worker-001",
                    "direct_queue": "browser.direct.test-worker-001",
                    "timestamp": str(now),
                },
            )
            redis_client.hset(
                "browser:affinity:session-002",
                mapping={
                    "worker_id": "test-worker-001",
                    "direct_queue": "browser.direct.test-worker-001",
                    "timestamp": str(now),
                },
            )

            # Pre-checks - verify setup worked
            assert redis_client.smembers("browser:worker_sessions:test-worker-001") == {
                "session-001",
                "session-002",
            }
            assert redis_client.exists("browser:affinity:session-001")
            assert redis_client.exists("browser:affinity:session-002")

        # Check cleanup
        assert not redis_client.exists("browser:worker:test-worker-001")
        assert not redis_client.exists("browser:worker_sessions:test-worker-001")
        assert not redis_client.exists("browser:affinity:session-001")
        assert not redis_client.exists("browser:affinity:session-002")

    def test_heartbeat_resilience_with_pipeline_errors(
        self, worker_lifecycle: WorkerLifecycle, redis_client: RedisLike, monkeypatch: MonkeyPatch
    ) -> None:
        """Test that heartbeat continues despite Redis pipeline errors."""
        worker_lifecycle.heartbeat_interval = 0.05
        worker_lifecycle.register()

        # Create a failing pipeline that recovers after 2 failures
        class FailingPipeline:
            def __init__(self, fail_count: int = 2) -> None:
                self.fail_count = fail_count
                self.commands: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

            def __enter__(self) -> "FailingPipeline":
                self.commands = []  # Clear commands on each pipeline usage
                return self

            def __exit__(
                self,
                exc_type: type[BaseException] | None,
                exc: BaseException | None,
                tb: TracebackType | None,
            ) -> Literal[False]:
                return False

            def hset(self, *args: Any, **kwargs: Any) -> "FailingPipeline":
                self.commands.append(("hset", args, kwargs))
                return self

            def expire(self, *args: Any, **kwargs: Any) -> "FailingPipeline":
                self.commands.append(("expire", args, kwargs))
                return self

            def execute(self) -> list[Any]:
                if self.fail_count > 0:
                    self.fail_count -= 1
                    raise RedisConnectionError("Simulated pipeline error")
                # After failures, execute normally
                for cmd, args, kwargs in self.commands:
                    getattr(redis_client, cmd)(*args, **kwargs)
                return [True] * len(self.commands)

        original_pipeline = redis_client.pipeline
        failing_pipeline = FailingPipeline(fail_count=2)
        monkeypatch.setattr(redis_client, "pipeline", lambda: failing_pipeline)

        with running_heartbeat(worker_lifecycle):
            time.sleep(0.3)  # Let it fail and recover

            # Restore normal pipeline
            monkeypatch.setattr(redis_client, "pipeline", original_pipeline)
            time.sleep(0.2)

            # Worker should still be registered
            assert redis_client.exists("browser:worker:test-worker-001")


class TestWorkerRegistry:
    """Test worker registry queries with proper mocking."""

    @pytest.fixture(autouse=True)
    def mock_settings(self, monkeypatch: MonkeyPatch) -> None:
        """Mock Settings to isolate tests from environment."""
        monkeypatch.setattr("swarm.distributed.worker_registry.Settings", lambda: MockSettings())

    @pytest.fixture
    def redis_client(self) -> RedisLike:
        """Provide a fake Redis client for testing."""
        return cast(RedisLike, FakeRedis(decode_responses=True))

    @pytest.fixture
    def registry(self, redis_client: RedisLike) -> WorkerRegistry:
        """Create a worker registry instance."""
        return WorkerRegistry(redis_client=cast(Any, redis_client))

    @pytest.fixture
    def setup_workers(self, redis_client: RedisLike) -> None:
        """Set up test workers in Redis."""
        # Worker 1: Healthy, low load
        redis_client.hset(
            "browser:worker:worker-001",
            mapping={
                "hostname": "worker-001",
                "capabilities": json.dumps(["browser", "chrome", "linux"]),
                "started_at": datetime.now(UTC).isoformat(),
                "last_heartbeat": datetime.now(UTC).isoformat(),
                "status": "active",
                "current_sessions": "2",
                "max_sessions": "10",
                "platform": "Linux",
                "python_version": "3.11.0",
            },
        )
        redis_client.expire("browser:worker:worker-001", 60)
        redis_client.sadd("browser:worker_sessions:worker-001", "session-001", "session-002")

        # Worker 2: Healthy, high load
        redis_client.hset(
            "browser:worker:worker-002",
            mapping={
                "hostname": "worker-002",
                "capabilities": json.dumps(["browser", "firefox", "linux", "gpu"]),
                "started_at": datetime.now(UTC).isoformat(),
                "last_heartbeat": datetime.now(UTC).isoformat(),
                "status": "active",
                "current_sessions": "8",
                "max_sessions": "10",
                "platform": "Linux",
                "python_version": "3.11.0",
            },
        )
        redis_client.expire("browser:worker:worker-002", 60)
        # No session set for worker-002 (testing empty case)

        # Worker 3: Dead (no heartbeat - simulated later)
        redis_client.hset(
            "browser:worker:worker-003",
            mapping={
                "hostname": "worker-003",
                "capabilities": json.dumps(["browser", "chrome", "windows"]),
                "started_at": datetime.now(UTC).isoformat(),
                "last_heartbeat": datetime.now(UTC).isoformat(),
                "status": "active",
                "current_sessions": "5",
                "max_sessions": "10",
                "platform": "Windows",
                "python_version": "3.11.0",
            },
        )
        redis_client.sadd("browser:worker_sessions:worker-003", "session-003")

    def test_get_healthy_workers(
        self, registry: WorkerRegistry, redis_client: RedisLike, setup_workers: None
    ) -> None:
        """Test retrieving only healthy workers."""
        # Provide heartbeats for worker-001/002 and simulate worker-003 missing
        redis_client.hset(
            "worker:heartbeat:browser:worker-001",
            mapping={
                "timestamp": str(time.time()),
                "worker_type": "browser",
                "worker_id": "worker-001",
            },
        )
        redis_client.hset(
            "worker:heartbeat:browser:worker-002",
            mapping={
                "timestamp": str(time.time()),
                "worker_type": "browser",
                "worker_id": "worker-002",
            },
        )
        # No heartbeat for worker-003 => considered dead by registry

        workers = registry.get_healthy_workers()
        assert len(workers) == 2

        worker_ids = {w.worker_id for w in workers}
        assert worker_ids == {"worker-001", "worker-002"}

    def test_find_least_loaded_worker(
        self, registry: WorkerRegistry, redis_client: RedisLike, setup_workers: None
    ) -> None:
        """Test finding the worker with lowest load."""
        # Heartbeats present for 001/002; 003 has none

        least_loaded = registry.find_least_loaded_worker()
        assert least_loaded == "worker-001"  # 20% load vs 80% load

    def test_orphaned_session_detection_with_proper_format(
        self, registry: WorkerRegistry, redis_client: RedisLike, setup_workers: None
    ) -> None:
        """Test finding sessions whose workers are dead with proper owner format."""
        # Set up session affinities with contract hash format
        now = time.time()
        for sid, wid in (
            ("session-001", "worker-001"),
            ("session-002", "worker-001"),
            ("session-003", "worker-003"),
            ("session-004", "worker-003"),
        ):
            redis_client.hset(
                f"browser:affinity:{sid}",
                mapping={
                    "worker_id": wid,
                    "direct_queue": f"browser.direct.{wid}",
                    "timestamp": str(now),
                },
            )

        # Establish liveness for worker-001 via standardized heartbeat
        redis_client.hset(
            "worker:heartbeat:browser:worker-001",
            mapping={
                "timestamp": str(time.time()),
                "worker_type": "browser",
                "worker_id": "worker-001",
            },
        )

        # Simulate worker-003 death by removing its heartbeat (if any)
        redis_client.delete("worker:heartbeat:browser:worker-003")

        orphaned = registry.get_orphaned_sessions()
        assert set(orphaned) == {"session-003", "session-004"}

    def test_cleanup_orphaned_sessions(
        self, registry: WorkerRegistry, redis_client: RedisLike, setup_workers: None
    ) -> None:
        """Test cleaning up orphaned sessions."""
        # Set up with contract hash format
        now = time.time()
        redis_client.hset(
            "browser:affinity:session-001",
            mapping={
                "worker_id": "worker-001",
                "direct_queue": "browser.direct.worker-001",
                "timestamp": str(now),
            },
        )
        redis_client.hset(
            "browser:affinity:session-003",
            mapping={
                "worker_id": "worker-003",
                "direct_queue": "browser.direct.worker-003",
                "timestamp": str(now),
            },
        )
        redis_client.hset(
            "browser:affinity:session-004",
            mapping={
                "worker_id": "worker-003",
                "direct_queue": "browser.direct.worker-003",
                "timestamp": str(now),
            },
        )

        # Establish liveness for worker-001 via standardized heartbeat
        redis_client.hset(
            "worker:heartbeat:browser:worker-001",
            mapping={
                "timestamp": str(time.time()),
                "worker_type": "browser",
                "worker_id": "worker-001",
            },
        )

        # Simulate worker-003 death by ensuring no heartbeat
        redis_client.delete("worker:heartbeat:browser:worker-003")

        cleaned_count = registry.cleanup_orphaned_sessions()
        assert cleaned_count == 2

        # Verify cleanup
        assert not redis_client.exists("browser:affinity:session-003")
        assert not redis_client.exists("browser:affinity:session-004")
        assert redis_client.exists("browser:affinity:session-001")


class TestBrowserRouterHealthCheck:
    """Test browser router health checking with proper scenarios."""

    @pytest.fixture(autouse=True)
    def mock_settings(self, monkeypatch: MonkeyPatch) -> None:
        """Mock Settings to isolate tests from environment."""
        monkeypatch.setattr("swarm.distributed.browser_router.Settings", lambda: MockSettings())

    @pytest.fixture
    def redis_client(self) -> RedisLike:
        """Provide a fake Redis client for testing."""
        return cast(RedisLike, FakeRedis(decode_responses=True))

    @pytest.mark.parametrize("task_name", ["browser.goto", "browser.click", "browser.screenshot"])
    def test_router_avoids_dead_workers(self, redis_client: RedisLike, task_name: str) -> None:
        """Test that router doesn't route to dead workers."""
        from swarm.distributed.browser_router import BrowserSessionRouter

        router = BrowserSessionRouter(redis_client=cast(Any, redis_client))
        worker_id = "worker-001"

        # Set up healthy heartbeat for worker
        redis_client.hset(
            f"worker:heartbeat:browser:{worker_id}",
            mapping={
                "timestamp": str(time.time()),
                "worker_type": "browser",
                "worker_id": worker_id,
            },
        )
        redis_client.expire(f"worker:heartbeat:browser:{worker_id}", 300)
        redis_client.sadd(f"browser:worker_sessions:{worker_id}", "session-001")

        # Set up session owned by healthy worker (contract hash)
        redis_client.hset(
            "browser:affinity:session-001",
            mapping={
                "worker_id": worker_id,
                "direct_queue": f"browser.direct.{worker_id}",
                "timestamp": str(time.time()),
            },
        )

        # Route should succeed to healthy worker
        route = router.route_for_task(task_name, kwargs={"session_id": "session-001"})
        assert route is not None
        assert route["queue"] == f"browser.direct.{worker_id}"
        assert route["exchange"] == f"browser.direct.{worker_id}"
        assert route["routing_key"] == f"browser.direct.{worker_id}"

        # Kill the worker heartbeat but KEEP the session set (important!)
        redis_client.delete(f"worker:heartbeat:browser:{worker_id}")
        # Session set remains: redis_client.exists(f"browser:worker_sessions:{worker_id}") == True

        # Route should now return None (fallback to default)
        route = router.route_for_task(task_name, kwargs={"session_id": "session-001"})
        assert route is None

        # Session ownership should be cleared
        assert not redis_client.exists("browser:affinity:session-001")

    def test_router_requires_heartbeat(self, redis_client: RedisLike) -> None:
        """Router does not route to workers without fresh heartbeat (authoritative)."""
        from swarm.distributed.browser_router import BrowserSessionRouter

        router = BrowserSessionRouter(redis_client=cast(Any, redis_client))
        worker_id = "no-heartbeat"

        # Affinity present but no heartbeat -> do not route, clear affinity
        redis_client.hset(
            "browser:affinity:session-001",
            mapping={
                "worker_id": worker_id,
                "direct_queue": f"browser.direct.{worker_id}",
                "timestamp": str(time.time()),
            },
        )
        route = router.route_for_task("browser.goto", kwargs={"session_id": "session-001"})
        assert route is None
        assert not redis_client.exists("browser:affinity:session-001")

    def test_router_cleanup_task_routing(self, redis_client: RedisLike) -> None:
        """Test that cleanup tasks go to browser queue."""
        from swarm.distributed.browser_router import BrowserSessionRouter

        router = BrowserSessionRouter(redis_client=cast(Any, redis_client))

        # Cleanup should always go to browser queue
        route = router.route_for_task("browser.cleanup", kwargs={"session_id": "session-001"})
        assert route == {"queue": "browser"}

    def test_router_redis_connection_recovery(
        self, redis_client: RedisLike, monkeypatch: MonkeyPatch
    ) -> None:
        """Test that router recovers from Redis connection errors."""
        from swarm.distributed.browser_router import BrowserSessionRouter

        router = BrowserSessionRouter(redis_client=cast(Any, redis_client))

        # Set up a healthy worker with heartbeat and affinity hash
        worker_id = "worker-001"
        redis_client.hset(
            f"worker:heartbeat:browser:{worker_id}",
            mapping={
                "timestamp": str(time.time()),
                "worker_type": "browser",
                "worker_id": worker_id,
            },
        )
        redis_client.expire(f"worker:heartbeat:browser:{worker_id}", 300)
        redis_client.sadd(f"browser:worker_sessions:{worker_id}", "session-001")
        redis_client.hset(
            "browser:affinity:session-001",
            mapping={
                "worker_id": worker_id,
                "direct_queue": f"browser.direct.{worker_id}",
                "timestamp": str(time.time()),
            },
        )

        # Simulate connection error then recovery
        call_count = {"count": 0}
        original_hget = redis_client.hget

        def failing_hget(*args: Any, **kwargs: Any) -> Any:
            call_count["count"] += 1
            if call_count["count"] <= 2:
                raise RedisConnectionError("Connection lost")
            return original_hget(*args, **kwargs)

        monkeypatch.setattr(redis_client, "hget", failing_hget)

        # First two attempts should fail gracefully
        route = router.route_for_task("browser.goto", kwargs={"session_id": "session-001"})
        assert route is None

        route = router.route_for_task("browser.goto", kwargs={"session_id": "session-001"})
        assert route is None

        # Third attempt: recovered, should route to worker
        route = router.route_for_task("browser.goto", kwargs={"session_id": "session-001"})
        assert route is not None
        assert route["queue"] == f"browser.direct.{worker_id}"
        assert route["exchange"] == f"browser.direct.{worker_id}"
        assert route["routing_key"] == f"browser.direct.{worker_id}"
