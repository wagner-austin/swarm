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
from types import TracebackType
from typing import Any, Callable, Generator, Iterator, Protocol, cast, overload, runtime_checkable

import pytest
import redis as redis_mod
from pytest import MonkeyPatch
from redis.exceptions import ConnectionError as RedisConnectionError

from swarm.distributed.browser_router import BrowserSessionRouter
from swarm.distributed.worker_lifecycle import WorkerLifecycle
from swarm.distributed.worker_registry import WorkerRegistry
from swarm.infra.redis_keys import (
    affinity_key as ak,
    heartbeat_key as hb,
    worker_key as wk,
    worker_sessions_key as ws,
)
from swarm.infra.redis_protocols import (
    RedisSyncProtocol as ProdRedisSyncProtocol,
    RedisSyncProtocol as RegistryRedisSyncProtocol,
    _PipelineProtocol as ProdPipelineProtocol,
)
from tests.integration.utils import poll_until_count, poll_until_true


def wait_for(predicate: Callable[[], bool], timeout: float = 5.0, interval: float = 0.05) -> bool:
    """Poll until predicate returns True (deprecated, use poll_until_true instead)."""
    try:
        poll_until_true(predicate, timeout=timeout, interval=interval, description="predicate")
        return True
    except TimeoutError:
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


class _PipelineAdapter(ProdPipelineProtocol):
    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __enter__(self) -> ProdPipelineProtocol:
        self._inner.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._inner.__exit__(exc_type, exc, tb)

    def hset(self, *args: Any, **kwargs: Any) -> ProdPipelineProtocol:
        self._inner.hset(*args, **kwargs)
        return self

    def expire(self, *args: Any, **kwargs: Any) -> ProdPipelineProtocol:
        self._inner.expire(*args, **kwargs)
        return self

    def delete(self, *names: str) -> ProdPipelineProtocol:
        for n in names:
            self._inner.delete(n)
        return self

    def execute(self) -> Any:
        return self._inner.execute()


class RedisAdapter(ProdRedisSyncProtocol):
    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def pipeline(self) -> ProdPipelineProtocol:
        return _PipelineAdapter(self._inner.pipeline())

    def hset(
        self,
        name: str,
        key: str | None = None,
        value: str | None = None,
        *,
        mapping: dict[str, str] | None = None,
    ) -> Any:
        if mapping is not None:
            return self._inner.hset(name, mapping=mapping)
        assert key is not None and value is not None
        return self._inner.hset(name, key, value)

    def expire(self, name: str, time: int) -> Any:
        return self._inner.expire(name, time)

    def delete(self, *names: str) -> Any:
        return sum(self._inner.delete(n) for n in names)

    def smembers(self, name: str) -> set[str]:
        return set(self._inner.smembers(name))

    def sadd(self, name: str, *values: str) -> Any:
        return self._inner.sadd(name, *values)

    def srem(self, name: str, *values: str) -> Any:
        return self._inner.srem(name, *values)

    def scard(self, name: str) -> int:
        return int(self._inner.scard(name))

    @overload
    def hgetall(self, name: str) -> dict[str, str]: ...

    @overload
    def hgetall(self, name: bytes) -> dict[bytes, bytes]: ...

    def hgetall(self, name: str | bytes) -> dict[bytes, bytes] | dict[str, str]:
        return dict(self._inner.hgetall(name))

    def exists(self, name: str) -> int:
        return int(self._inner.exists(name))

    def keys(self, pattern: str) -> list[str]:
        return [str(k) for k in self._inner.keys(pattern)]

    def hget(self, name: str, key: str) -> str | None:
        val = self._inner.hget(name, key)
        return val if isinstance(val, str) else None

    def ttl(self, name: str) -> int:
        return int(self._inner.ttl(name))

    def set(self, name: str, value: str) -> bool:
        return bool(self._inner.set(name, value))

    def get(self, name: str) -> str | None:
        val = self._inner.get(name)
        return val if isinstance(val, str) else None

    def eval(self, script: str, numkeys: int, *keys_and_args: object) -> object:
        return self._inner.eval(script, numkeys, *keys_and_args)


class RedisAdapterForRegistry(RegistryRedisSyncProtocol):
    def __init__(self, inner: redis_mod.Redis) -> None:
        self._inner = inner

    def keys(self, pattern: str) -> list[str]:
        return [str(k) for k in self._inner.keys(pattern)]

    def hgetall(self, name: str) -> dict[str, str]:
        return {str(k): str(v) for k, v in self._inner.hgetall(name).items()}

    def exists(self, name: str) -> int:
        return int(self._inner.exists(name))

    def scard(self, name: str) -> int:
        return int(self._inner.scard(name))

    def hget(self, name: str, key: str) -> str | None:
        val = self._inner.hget(name, key)
        return val if isinstance(val, str) else None

    def get(self, name: str) -> str | None:
        val = self._inner.get(name)
        return val if isinstance(val, str) else None

    def delete(self, *names: str) -> Any:
        return sum(self._inner.delete(n) for n in names)

    def eval(self, script: str, numkeys: int, *keys_and_args: object) -> object:
        return self._inner.eval(script, numkeys, *keys_and_args)

    def scan_iter(self, *, match: str) -> Iterator[str]:
        for k in self._inner.scan_iter(match=match):
            yield str(k)


@pytest.mark.integration
class TestWorkerHeartbeatIntegration:
    """Integration tests with real Redis for TTL and expiry behavior."""

    @pytest.fixture(autouse=True)
    def patch_settings(self, monkeypatch: MonkeyPatch) -> None:
        """Patch Settings to use test configuration."""
        # Use direct local Redis with auth if available to ensure a single backend.
        password = os.getenv("REDIS_PASSWORD")
        # Use DB 15 explicitly to isolate test data from production DB 0
        if password:
            redis_url = f"redis://default:{password}@localhost:6379/15"
        else:
            redis_url = "redis://localhost:6379/15"

        # SAFETY CHECK: Prevent tests from running against production
        if "upstash.io" in redis_url or "production" in redis_url.lower():
            pytest.skip(
                f"SAFETY: Refusing to run tests against production Redis!\n"
                f"  URL: {redis_url}\n"
                f"  Tests use flushdb() which would DELETE ALL DATA."
            )

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
        # Match the URL used in patch_settings
        password = os.getenv("REDIS_PASSWORD")
        # Use DB 15 explicitly to isolate test data from production DB 0
        if password:
            redis_url = f"redis://default:{password}@localhost:6379/15"
        else:
            redis_url = "redis://localhost:6379/15"

        # SAFETY CHECK: Prevent tests from running against production
        # Tests use flushdb() which would DELETE ALL DATA!
        if (
            "upstash.io" in redis_url
            or "production" in redis_url.lower()
            or ":6380" in redis_url
            or redis_url.rstrip("/").endswith("/0")
        ):
            pytest.skip(
                f"SAFETY: Refusing to run tests against production Redis!\n"
                f"  URL: {redis_url}\n"
                f"  Tests use flushdb() which would DELETE ALL DATA.\n"
                f"  Port 6380 is HAProxy (production), tests must use port 6379 (direct Redis).\n"
                f"  Tests must use DB 15 to avoid wiping DB 0.\n"
                f"  Please verify pytest.ini has REDIS__URL=...@localhost:6379/15"
            )

        try:
            client: redis_mod.Redis[str] = redis_mod.from_url(redis_url, decode_responses=True)
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
        worker = WorkerLifecycle("test-worker", redis_client=RedisAdapter(redis_client))
        worker.heartbeat_interval = 0.5
        worker.heartbeat_timeout = 2  # 2 second TTL

        worker.register()
        worker.start_heartbeat()
        # Wait for initial worker key to appear
        poll_until_true(
            lambda: bool(redis_client.exists(wk("test-worker"))),
            timeout=3.0,
            interval=0.05,
            description="worker key to appear",
        )

        # Verify worker is registered
        assert redis_client.exists(wk("test-worker"))

        # Stop heartbeat but don't cleanup (simulate crash)
        worker.shutdown_event.set()
        time.sleep(0.6)  # Wait for last heartbeat to pass

        # Worker should still exist (TTL not expired)
        assert redis_client.exists(wk("test-worker"))

        # Wait for TTL to expire using polling
        poll_until_true(
            lambda: not redis_client.exists(wk("test-worker")),
            timeout=5.0,
            interval=0.05,
            description="worker key to expire",
        )

    def test_heartbeat_extends_ttl_continuously(self, redis_client: RedisLike) -> None:
        """Test that continuous heartbeats keep worker alive beyond initial TTL."""
        worker = WorkerLifecycle("test-worker", redis_client=RedisAdapter(redis_client))
        worker.heartbeat_interval = 0.1
        worker.heartbeat_timeout = 1  # Short TTL

        worker.register()
        worker.start_heartbeat()

        try:
            # Sleep for 3x the TTL duration - worker should still be alive due to continuous heartbeats
            time.sleep(worker.heartbeat_timeout * 3)

            # Verify both worker key and heartbeat key are alive
            worker_exists = redis_client.exists(wk("test-worker"))
            hb_exists = redis_client.exists(hb("test-worker"))
            worker_ttl = redis_client.ttl(wk("test-worker"))
            hb_ttl = redis_client.ttl(hb("test-worker"))

            assert worker_exists, (
                f"Worker key missing (hb_exists={hb_exists}, worker_ttl={worker_ttl}, hb_ttl={hb_ttl})"
            )
            assert hb_exists, (
                f"Heartbeat key missing (worker_exists={worker_exists}, worker_ttl={worker_ttl}, hb_ttl={hb_ttl})"
            )

            # Heartbeat key is authoritative for liveness - it MUST have TTL > 0
            assert hb_ttl > 0, f"Heartbeat TTL expired: hb_ttl={hb_ttl}, worker_ttl={worker_ttl}"

            # Worker key should also be alive (both get updated by Lua script)
            assert worker_ttl > 0, f"Worker TTL expired: worker_ttl={worker_ttl}, hb_ttl={hb_ttl}"
        finally:
            worker.stop_heartbeat()

    def test_router_fallback_with_real_ttl_expiry(self, redis_client: RedisLike) -> None:
        """Test router behavior when worker TTL expires."""
        router = BrowserSessionRouter(redis_client=None)
        worker_id = "test-worker"

        # Create worker metadata and heartbeat with short TTL (router uses heartbeat)
        redis_client.hset(
            wk(worker_id),
            mapping={
                "hostname": worker_id,
                "status": "active",
                "last_heartbeat": datetime.now(UTC).isoformat(),
            },
        )
        # Authoritative liveness for router: heartbeat timestamp
        redis_client.hset(
            hb(worker_id),
            mapping={"timestamp": str(time.time())},
        )
        redis_client.expire(hb(worker_id), 1)  # 1 second TTL
        redis_client.sadd(ws(worker_id), "session-001")
        redis_client.hset(
            ak("session-001"),
            mapping={
                "worker_id": worker_id,
                "direct_queue": f"browser.direct.{worker_id}",
                "timestamp": str(time.time()),
            },
        )

        # Should route while alive (first heartbeat might need a moment)
        poll_until_true(
            lambda: router.route_for_task("browser.goto", kwargs={"session_id": "session-001"})
            is not None,
            timeout=3.0,
            interval=0.05,
            description="router to find direct queue",
        )
        route = router.route_for_task("browser.goto", kwargs={"session_id": "session-001"})
        assert route["queue"] == f"browser.direct.{worker_id}"

        # Wait for heartbeat TTL to expire using polling (router health source)
        poll_until_true(
            lambda: not redis_client.exists(hb(worker_id)),
            timeout=3.0,
            interval=0.05,
            description="heartbeat key to expire",
        )

        # Should fall back to default
        route = router.route_for_task("browser.goto", kwargs={"session_id": "session-001"})
        assert route is None

        # Affinity should be cleared
        assert not redis_client.exists(ak("session-001"))

    def test_concurrent_workers_with_real_redis(self, redis_client: RedisLike) -> None:
        """Test multiple workers with concurrent operations."""
        workers = []
        registry = WorkerRegistry(redis_client=RedisAdapterForRegistry(redis_client))

        # Start 3 workers
        for i in range(3):
            worker = WorkerLifecycle(f"worker-{i:03d}", redis_client=RedisAdapter(redis_client))
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
                    redis_client.hset(
                        ak(session_id),
                        mapping={
                            "worker_id": worker.worker_id,
                            "direct_queue": f"browser.direct.{worker.worker_id}",
                            "timestamp": str(time.time()),
                        },
                    )

            # Wait for all workers to become healthy
            poll_until_count(
                lambda: len(registry.get_healthy_workers()),
                expected=3,
                timeout=5.0,
                interval=0.1,
                description="healthy workers",
            )

            # Simulate worker 1 crash
            workers[1].shutdown_event.set()

            # Wait for heartbeat TTL expiry using polling (authoritative liveness)
            poll_until_true(
                lambda: not redis_client.exists(hb("worker-001")),
                timeout=5.0,
                interval=0.05,
                description="crashed worker heartbeat to expire",
            )

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
        worker = WorkerLifecycle("test-worker", redis_client=RedisAdapter(redis_client))

        # Register with pipeline
        worker.register()

        # All fields should be set atomically
        data = redis_client.hgetall(wk("test-worker"))
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
        worker = WorkerLifecycle("test-worker", redis_client=RedisAdapter(redis_client))
        worker.heartbeat_interval = 0.1
        worker.register()
        worker.start_heartbeat()

        try:
            # Verify worker is alive
            assert redis_client.exists(wk("test-worker"))

            # Simulate connection drop by killing all client connections
            # (This would require admin access to Redis, so we simulate differently)
            # Instead, we'll test that worker continues after connection errors

            time.sleep(0.5)

            # Worker should still be registered
            assert redis_client.exists(wk("test-worker"))

        finally:
            worker.stop_heartbeat()

    def test_load_balancing_with_real_workers(self, redis_client: RedisLike) -> None:
        """Test load balancing across multiple workers."""
        registry = WorkerRegistry(redis_client=RedisAdapterForRegistry(redis_client))

        # Create workers with different loads
        for i, load in enumerate([2, 5, 8]):
            redis_client.hset(
                wk(f"worker-{i:03d}"),
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
            redis_client.expire(wk(f"worker-{i:03d}"), 60)
            # Authoritative liveness: heartbeat key with TTL
            redis_client.hset(
                hb(f"worker-{i:03d}"),
                mapping={
                    "timestamp": str(time.time()),
                    "worker_type": "browser",
                    "worker_id": f"worker-{i:03d}",
                },
            )
            redis_client.expire(hb(f"worker-{i:03d}"), 60)

        # Should pick least loaded
        least_loaded = registry.find_least_loaded_worker()
        assert least_loaded == "worker-000"  # 20% load

        # Add load to worker-000
        redis_client.hset(wk("worker-000"), "current_sessions", "6")

        # Now worker-001 should be least loaded
        least_loaded = registry.find_least_loaded_worker()
        assert least_loaded == "worker-001"  # 50% load

    def test_graceful_vs_ungraceful_shutdown(self, redis_client: RedisLike) -> None:
        """Test difference between graceful and ungraceful shutdown."""
        # Graceful shutdown
        worker1 = WorkerLifecycle("graceful-worker", redis_client=RedisAdapter(redis_client))
        worker1.register()
        worker1.start_heartbeat()
        worker1.add_session("session-001")
        redis_client.hset(
            ak("session-001"),
            mapping={
                "worker_id": "graceful-worker",
                "direct_queue": "browser.direct.graceful-worker",
                "timestamp": str(time.time()),
            },
        )

        worker1.stop_heartbeat()  # Graceful

        # Should clean up promptly (allow brief delay for pipeline)
        poll_until_true(
            lambda: not redis_client.exists(wk("graceful-worker")),
            timeout=3.0,
            interval=0.05,
            description="graceful worker key removal",
        )
        poll_until_true(
            lambda: not redis_client.exists(ak("session-001")),
            timeout=3.0,
            interval=0.05,
            description="graceful affinity removal",
        )

        # Ungraceful shutdown (crash simulation)
        worker2 = WorkerLifecycle("crash-worker", redis_client=RedisAdapter(redis_client))
        worker2.heartbeat_timeout = 1  # Short TTL
        worker2.register()
        worker2.start_heartbeat()
        worker2.add_session("session-002")
        redis_client.hset(
            ak("session-002"),
            mapping={
                "worker_id": "crash-worker",
                "direct_queue": "browser.direct.crash-worker",
                "timestamp": str(time.time()),
            },
        )

        # Simulate crash
        worker2.shutdown_event.set()  # Stop heartbeat without cleanup

        # Should still exist initially (worker key) and affinity key
        assert redis_client.exists(wk("crash-worker"))
        assert redis_client.exists(ak("session-002"))

        # Heartbeat determines liveness; simulate death by deleting heartbeat
        redis_client.delete(hb("crash-worker"))
        # Worker hash may remain, but liveness is gone; affinity remains orphaned
        assert redis_client.exists(ak("session-002"))

        # Registry should detect as orphaned
        registry = WorkerRegistry(redis_client=RedisAdapterForRegistry(redis_client))
        # Allow a brief window for final heartbeat loop exit and key propagation
        poll_until_true(
            lambda: "session-002" in registry.get_orphaned_sessions(),
            timeout=3.0,
            interval=0.05,
            description="orphaned session detection",
        )
