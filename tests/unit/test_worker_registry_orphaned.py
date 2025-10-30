from __future__ import annotations

import json
import time
from datetime import UTC, datetime

import fakeredis
import pytest

from swarm.distributed.session_registry import SessionRegistry
from swarm.distributed.worker_registry import WorkerRegistry
from swarm.infra.redis_keys import (
    affinity_key as ak,
    heartbeat_key as hb,
    worker_key as wk,
    worker_sessions_key as ws,
)


def _make_worker(redis: fakeredis.FakeRedis, wid: str, *, healthy: bool) -> None:
    now = datetime.now(UTC).isoformat()
    redis.hset(
        wk(wid),
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
    hb_key = hb(wid)
    # Create heartbeat key with proper metadata
    redis.hset(
        hb_key, mapping={"timestamp": str(time.time()), "worker_type": "browser", "worker_id": wid}
    )
    if healthy:
        redis.expire(hb_key, 60)
    else:
        # Leave ttl at 0 (default) -> dead
        pass


@pytest.mark.unit
def test_get_orphaned_sessions_computes_from_dead_workers() -> None:
    r = fakeredis.FakeRedis(decode_responses=True)

    # Create workers: worker-001 (dead), worker-002 (alive)
    _make_worker(r, "worker-001", healthy=False)
    _make_worker(r, "worker-002", healthy=True)

    # Sessions owned by workers (aux index) and canonical affinity mapping
    r.sadd(ws("worker-001"), "session-a", "session-b")
    r.sadd(ws("worker-002"), "session-c")

    now = time.time()
    # Canonical affinity hashes (authoritative ownership)
    r.hset(
        ak("session-a"),
        mapping={
            "worker_id": "worker-001",
            "direct_queue": "browser.direct.worker-001",
            "timestamp": str(now),
        },
    )
    r.hset(
        ak("session-b"),
        mapping={
            "worker_id": "worker-001",
            "direct_queue": "browser.direct.worker-001",
            "timestamp": str(now),
        },
    )
    r.hset(
        ak("session-c"),
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
    r = fakeredis.FakeRedis(decode_responses=True)

    called = {"flag": False}
    expected = ["x", "y"]

    def _fake_find(client: fakeredis.FakeRedis) -> list[str]:
        called["flag"] = True
        # Verify we received the same client instance
        assert isinstance(client, fakeredis.FakeRedis)
        return list(expected)

    monkeypatch.setattr(SessionRegistry, "find_orphaned_sessions_sync", staticmethod(_fake_find))

    reg = WorkerRegistry(redis_client=r)
    result = reg.get_orphaned_sessions()
    assert called["flag"] is True
    assert result == expected


@pytest.mark.unit
def test_heartbeat_ttl_positive_not_orphan() -> None:
    """TTL > 0 means not orphan."""
    r = fakeredis.FakeRedis(decode_responses=True)
    # Create affinity for one session
    r.hset(
        ak("session-b"),
        mapping={
            "worker_id": "wid",
            "direct_queue": "browser.direct.wid",
            "timestamp": str(time.time()),
        },
    )
    # TTL positive -> healthy
    r.hset(
        hb("wid"),
        mapping={"timestamp": str(time.time()), "worker_type": "browser", "worker_id": "wid"},
    )
    r.expire(hb("wid"), 60)

    orphans = SessionRegistry.find_orphaned_sessions_sync(r)
    assert "session-b" not in orphans


@pytest.mark.unit
def test_heartbeat_ttl_zero_is_orphan() -> None:
    """TTL <= 0 means orphaned."""
    r = fakeredis.FakeRedis(decode_responses=True)
    r.hset(
        ak("session-c"),
        mapping={
            "worker_id": "wid2",
            "direct_queue": "browser.direct.wid2",
            "timestamp": str(time.time()),
        },
    )
    # No TTL set -> dead
    r.hset(
        hb("wid2"),
        mapping={"timestamp": str(time.time()), "worker_type": "browser", "worker_id": "wid2"},
    )

    orphans = SessionRegistry.find_orphaned_sessions_sync(r)
    assert "session-c" in orphans
