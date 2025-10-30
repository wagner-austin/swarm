"""
Browser Session Registry

Deterministic session-to-worker mapping using straightforward Redis primitives
for writes and reads. Delegates batch TTL liveness checks to a shared, typed
Lua helper to avoid drift and reduce round-trips.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, TypedDict

import redis.asyncio as redis_asyncio

from swarm.core.settings import Settings
from swarm.infra import async_close_redis
from swarm.infra.redis_keys import (
    AFFINITY_PREFIX,
    HEARTBEAT_PREFIX,
    affinity_key,
    affinity_scan_pattern,
    heartbeat_key,
    session_id_from_affinity_key,
    worker_sessions_key,
)
from swarm.infra.redis_lua import orphaned_sessions_by_scan_sync
from swarm.infra.redis_protocols import (
    RedisAsyncProtocol,
    RedisSyncProtocol,
    wrap_redis_async,
)
from swarm.utils.worker_identity import direct_queue_name

logger = logging.getLogger(__name__)

# TTL and intervals are sourced from Settings at instance creation to avoid drift.


class SessionRegistry:
    """
    Session registry for browser session affinity.

    Uses one key per session with built-in expiry to avoid memory leaks and
    ensures deterministic routing across workers.
    """

    def __init__(self, redis_client: RedisAsyncProtocol | None = None) -> None:
        """Initialize session registry with Redis client."""
        self._redis: RedisAsyncProtocol | None = redis_client
        cfg = Settings()
        self._ttl: int = int(cfg.sessions.ttl_seconds)

    async def _get_redis(self) -> RedisAsyncProtocol:
        """Get or create Redis client."""
        if self._redis is None:
            settings = Settings()
            if not settings.redis.url:
                raise ValueError("Redis URL not configured")

            logger.info(f"SessionRegistry connecting to Redis URL: {settings.redis.url}")

            inner = redis_asyncio.from_url(
                settings.redis.url,
                decode_responses=True,  # Return strings instead of bytes
                socket_connect_timeout=2,  # Reasonable connect timeout
                socket_timeout=3,  # Allow brief HAProxy/backend delays
            )
            self._redis = wrap_redis_async(inner)

        assert self._redis is not None
        return self._redis

    async def set_owner(self, session_id: str, worker_id: str) -> bool:
        """
        Set the worker that owns a browser session.

        Uses SETEX for atomic operation with built-in TTL.
        Note: We use SETEX which overwrites any existing value. In practice,
        the router only sets owner after confirming no owner exists.

        Args:
            session_id: Unique session identifier
            worker_id: Worker hostname that owns the session

        Returns:
            True if set successfully
        """
        redis = await self._get_redis()

        try:
            # One key per session: authoritative hash with TTL
            session_key = affinity_key(session_id)

            # Canonical direct queue naming (host-only id)
            direct_queue = direct_queue_name(worker_id)

            record: AffinityRecord = {
                "worker_id": worker_id,
                "direct_queue": direct_queue,
                "timestamp": str(time.time()),
            }
            await redis.hset(session_key, mapping=_affinity_mapping(record))
            await redis.expire(session_key, self._ttl)

            logger.debug(
                f"Set session {session_id} owner to worker {worker_id} with {direct_queue}"
            )
            return True

        except Exception as exc:
            logger.error(f"Failed to set session owner for {session_id}: {exc!r}", exc_info=True)
            return False

    async def clear_owner(self, session_id: str) -> bool:
        """
        Clear the owner of a browser session.

        Args:
            session_id: Session to clear

        Returns:
            True if cleared successfully
        """
        redis = await self._get_redis()

        try:
            session_key = affinity_key(session_id)

            # Best-effort: try to remove from session set, but ignore errors
            data = await redis.hgetall(session_key)
            owner = data.get("worker_id") if data else None
            if owner:
                sessions_key = worker_sessions_key(owner)
                try:
                    await redis.srem(sessions_key, session_id)
                except Exception:
                    pass  # Best effort cleanup

            # Delete the affinity key
            await redis.delete(session_key)

            logger.info(f"Cleared session {session_id} owner")
            return True

        except Exception as exc:
            logger.error(f"Failed to clear session owner for {session_id}: {exc!r}")
            return False

    async def get_session_owner(self, session_id: str) -> str | None:
        """
        Get the worker that owns a session.

        Also refreshes the TTL if less than half remaining to keep
        long-running sessions alive without making them immortal.

        Args:
            session_id: Session to look up

        Returns:
            Worker ID if found, None otherwise
        """
        redis = await self._get_redis()

        try:
            session_key = affinity_key(session_id)

            # Get current owner
            worker_id = await redis.hget(session_key, "worker_id")
            if not worker_id:
                return None

            # Refresh TTL only if less than half remaining
            ttl = await redis.ttl(session_key)
            if 0 < ttl < self._ttl // 2 or ttl == -1:
                await redis.expire(session_key, self._ttl)

            return str(worker_id)

        except Exception as exc:
            logger.error(f"Failed to get session owner for {session_id}: {exc!r}")
            return None

    async def close(self) -> None:
        """Close Redis connection."""
        if self._redis:
            await async_close_redis(self._redis)

    # -----------------
    # Orphan detection (sync helper to avoid drift in registries)
    # -----------------
    @staticmethod
    def find_orphaned_sessions_sync(client: RedisSyncProtocol) -> list[str]:
        """Return sessions whose owning worker heartbeat is missing.

        Uses TTL on standardized heartbeat keys (authoritative). A worker is
        live iff TTL(key) > 0.
        """
        try:
            pattern = affinity_scan_pattern()
            return orphaned_sessions_by_scan_sync(
                client,
                affinity_match_pattern=pattern,
                heartbeat_prefix=HEARTBEAT_PREFIX,
                affinity_prefix=AFFINITY_PREFIX,
                scan_count=1000,
            )
        except Exception as exc:
            logger.error(f"Failed to compute orphaned sessions (sync): {exc}")
            return []


# Note on concurrency:
# - We assume cleanup happens after all actions complete (no mid-flight cleanup)
# - SETEX is atomic, preventing accidental overwrites
# - TTL refresh on read keeps long-running sessions alive
# - No background cleanup needed - Redis handles expiry automatically
# Typed hash schema for affinity entries in Redis
class AffinityRecord(TypedDict):
    worker_id: str
    direct_queue: str
    timestamp: str


def _affinity_mapping(a: AffinityRecord) -> dict[str, str]:
    """Convert AffinityRecord to a concrete dict[str, str] for Redis API."""
    return {
        "worker_id": a["worker_id"],
        "direct_queue": a["direct_queue"],
        "timestamp": a["timestamp"],
    }
