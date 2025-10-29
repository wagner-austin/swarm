from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Dict

import pytest

from swarm.distributed.session_registry import SessionRegistry
from swarm.distributed.worker_registry import WorkerRegistry
from swarm.infra.redis_protocols import RedisSyncProtocol


class _FakeRedis(RedisSyncProtocol):
    def __init__(self) -> None:
        self._kv: dict[str, dict[str, str]] = {}
        self._sets: dict[str, set[str]] = {}

    # Hash operations
    def hset(
        self,
        name: str,
        key: str | None = None,
        value: str | None = None,
        *,
        mapping: dict[str, str] | None = None,
    ) -> int:
        m = self._kv.setdefault(name, {})
        if mapping is not None:
            for k, v in mapping.items():
                m[str(k)] = str(v)
            return len(mapping)
        assert key is not None and value is not None
        m[str(key)] = str(value)
        return 1

    def hget(self, name: str, key: str) -> str | None:
        return self._kv.get(name, {}).get(key)

    def hgetall(self, name: str) -> dict[str, str]:
        return dict(self._kv.get(name, {}))

    # String operations (not used here)
    def setex(self, name: str, time: int, value: str) -> bool:  # noqa: A003 (shadow builtin)
        self._kv.setdefault(name, {})["value"] = str(value)
        return True

    # Key operations
    def delete(self, *names: str) -> int:
        count = 0
        for n in names:
            if n in self._kv:
                del self._kv[n]
                count += 1
        return count

    def keys(self, pattern: str) -> list[str]:
        # Support simple prefix* patterns used by registry
        if pattern.endswith("*"):
            prefix = pattern[:-1]
            return [k for k in self._kv.keys() if k.startswith(prefix)]
        return [k for k in self._kv.keys() if k == pattern]

    def exists(self, name: str) -> int:
        return 1 if name in self._kv else 0

    # Set operations
    def smembers(self, name: str) -> set[str]:
        return set(self._sets.get(name, set()))

    def sadd(self, name: str, *values: str) -> int:
        s = self._sets.setdefault(name, set())
        before = len(s)
        for v in values:
            s.add(str(v))
        return len(s) - before

    def srem(self, name: str, *values: str) -> int:
        s = self._sets.setdefault(name, set())
        before = len(s)
        for v in values:
            s.discard(str(v))
        return before - len(s)

    def scard(self, name: str) -> int:
        return len(self._sets.get(name, set()))

    # TTL operations
    def expire(self, name: str, ttl: int) -> bool:  # noqa: ARG002
        return True

    # Pipeline
    def pipeline(self):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    # Lifecycle
    def close(self) -> None:
        pass


def _make_worker(redis: _FakeRedis, wid: str, *, healthy: bool) -> None:
    now = datetime.now(UTC).isoformat()
    redis.hset(
        f"browser:worker:{wid}",
        mapping={
            "hostname": wid,
            "capabilities": json.dumps([]),
            "started_at": now,
            "last_heartbeat": now,
            "status": "active",
            "current_sessions": "0",
            "max_sessions": "10",
            "platform": "linux",
            "python_version": "3.11",
        },
    )
    if healthy:
        redis.hset(
            f"worker:heartbeat:browser:{wid}",
            mapping={"timestamp": str(time.time())},
        )
    else:
        # No timestamp -> considered dead by registry
        redis.hset(f"worker:heartbeat:browser:{wid}", mapping={})


@pytest.mark.unit
def test_get_orphaned_sessions_computes_from_dead_workers() -> None:
    r = _FakeRedis()

    # Create workers: worker-001 (dead), worker-002 (alive)
    _make_worker(r, "worker-001", healthy=False)
    _make_worker(r, "worker-002", healthy=True)

    # Sessions owned by workers (aux index) and canonical affinity mapping
    r.sadd("browser:worker_sessions:worker-001", "session-a", "session-b")
    r.sadd("browser:worker_sessions:worker-002", "session-c")

    now = time.time()
    # Canonical affinity hashes (authoritative ownership)
    r.hset(
        "browser:affinity:session-a",
        mapping={
            "worker_id": "worker-001",
            "direct_queue": "browser.direct.worker-001",
            "timestamp": str(now),
        },
    )
    r.hset(
        "browser:affinity:session-b",
        mapping={
            "worker_id": "worker-001",
            "direct_queue": "browser.direct.worker-001",
            "timestamp": str(now),
        },
    )
    r.hset(
        "browser:affinity:session-c",
        mapping={
            "worker_id": "worker-002",
            "direct_queue": "browser.direct.worker-002",
            "timestamp": str(now),
        },
    )

    reg = WorkerRegistry(redis_client=r)

    orphans = sorted(reg.get_orphaned_sessions())
    assert orphans == ["session-a", "session-b"]


@pytest.mark.unit
def test_worker_registry_delegates_to_session_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: WorkerRegistry should delegate orphan detection to SessionRegistry.

    Prevents drift where multiple code paths attempt to compute orphans differently.
    """
    r = _FakeRedis()

    called = {"flag": False}
    expected = ["x", "y"]

    def _fake_find(client: RedisSyncProtocol, *, stale_seconds: float = 90.0) -> list[str]:  # noqa: ARG001
        called["flag"] = True
        # Verify we received the same client instance
        assert isinstance(client, _FakeRedis)
        return list(expected)

    monkeypatch.setattr(SessionRegistry, "find_orphaned_sessions_sync", staticmethod(_fake_find))

    reg = WorkerRegistry(redis_client=r)
    result = reg.get_orphaned_sessions()
    assert called["flag"] is True
    assert result == expected


@pytest.mark.unit
def test_heartbeat_fresh_borderline_not_orphan() -> None:
    """Exactly at stale threshold should be considered fresh (not orphan)."""
    r = _FakeRedis()
    # Create affinity for one session
    r.hset(
        "browser:affinity:session-b",
        mapping={
            "worker_id": "wid",
            "direct_queue": "browser.direct.wid",
            "timestamp": str(time.time()),
        },
    )
    # Heartbeat exactly at threshold (90.0s ago) -> not stale
    ts = time.time() - 90.0
    r.hset("worker:heartbeat:browser:wid", mapping={"timestamp": str(ts)})

    orphans = SessionRegistry.find_orphaned_sessions_sync(r, stale_seconds=90.0)
    assert "session-b" not in orphans


@pytest.mark.unit
def test_heartbeat_stale_borderline_is_orphan() -> None:
    """Slightly older than stale threshold is considered orphaned."""
    r = _FakeRedis()
    r.hset(
        "browser:affinity:session-c",
        mapping={
            "worker_id": "wid2",
            "direct_queue": "browser.direct.wid2",
            "timestamp": str(time.time()),
        },
    )
    # Heartbeat slightly older than threshold
    ts = time.time() - 90.001
    r.hset("worker:heartbeat:browser:wid2", mapping={"timestamp": str(ts)})

    orphans = SessionRegistry.find_orphaned_sessions_sync(r, stale_seconds=90.0)
    assert "session-c" in orphans
