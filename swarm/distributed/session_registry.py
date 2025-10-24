"""
Minimal Browser Session Registry for Phase 1

Simple session-to-worker mapping for deterministic routing.
No Lua scripts, no complexity - just what's needed to fix test flakiness.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

import redis.asyncio as redis_asyncio

from swarm.core.settings import Settings
from swarm.infra import async_close_redis

if TYPE_CHECKING:
    # For type checking, Redis is generic
    from redis.asyncio import Redis as _Redis

    RedisAsyncClient = _Redis[Any]
else:
    # At runtime, Redis is not generic
    RedisAsyncClient = redis_asyncio.Redis

logger = logging.getLogger(__name__)

# Affinity key prefix - separate from session metadata
AFFINITY_PREFIX = "browser:affinity:"

# Session TTL in seconds (1 hour)
SESSION_TTL = 3600


class SessionRegistry:
    """
    Minimal session registry for browser session affinity.

    Phase 1: Simple session-to-worker mapping with basic Redis operations.
    Uses one key per session with built-in expiry to avoid memory leaks.
    """

    def __init__(self, redis_client: RedisAsyncClient | None = None) -> None:
        """Initialize session registry with Redis client."""
        self._redis: RedisAsyncClient | None = redis_client

    async def _get_redis(self) -> RedisAsyncClient:
        """Get or create Redis client."""
        if self._redis is None:
            settings = Settings()
            if not settings.redis.url:
                raise ValueError("Redis URL not configured")

            logger.info(f"SessionRegistry connecting to Redis URL: {settings.redis.url}")
            self._redis = redis_asyncio.from_url(
                settings.redis.url,
                decode_responses=True,  # Return strings instead of bytes
                socket_connect_timeout=1,  # Fast fail on connection issues
                socket_timeout=1,  # Fast fail on operations
            )

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
            # One key per session with built-in expiry
            # No need for separate TTL key or hash scanning
            # Use affinity namespace separate from session metadata
            session_key = f"{AFFINITY_PREFIX}{session_id}"
            logger.debug(f"About to SETEX key={session_key}, ttl={SESSION_TTL}, value={worker_id}")
            result = await redis.setex(session_key, SESSION_TTL, worker_id)
            logger.debug(f"SETEX result: {result}")

            # Verify it was actually written
            check = await redis.get(session_key)
            logger.debug(f"Verification GET returned: {check}")

            # Do NOT add the session to worker_sessions here.
            # Only the worker itself should claim it once the task starts.

            logger.debug(f"Set session {session_id} owner to worker {worker_id}")
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
            session_key = f"{AFFINITY_PREFIX}{session_id}"

            # Best-effort: try to remove from session set, but ignore errors
            owner = await redis.get(session_key)
            if owner:
                clean_worker_id = owner.split("_", 1)[1] if "_" in owner else owner
                sessions_key = f"browser:worker_sessions:{clean_worker_id}"
                try:
                    await redis.srem(sessions_key, session_id)  # type: ignore[attr-defined]
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
            session_key = f"{AFFINITY_PREFIX}{session_id}"

            # Get current owner
            worker_id = await redis.get(session_key)
            if not worker_id:
                return None

            # Refresh TTL only if less than half remaining
            # This prevents polling from making sessions immortal
            ttl = await redis.ttl(session_key)  # type: ignore[attr-defined]
            if 0 < ttl < SESSION_TTL // 2 or ttl == -1:
                await redis.expire(session_key, SESSION_TTL)

            return str(worker_id)

        except Exception as exc:
            logger.error(f"Failed to get session owner for {session_id}: {exc!r}")
            return None

    async def close(self) -> None:
        """Close Redis connection."""
        if self._redis:
            await async_close_redis(self._redis)


# Note on concurrency:
# - We assume cleanup happens after all actions complete (no mid-flight cleanup)
# - SETEX is atomic, preventing accidental overwrites
# - TTL refresh on read keeps long-running sessions alive
# - No background cleanup needed - Redis handles expiry automatically
