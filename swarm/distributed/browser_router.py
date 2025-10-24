"""
Celery Router for Browser Session Affinity

Routes browser tasks to workers that own the session, enabling
deterministic task execution across multiple workers.
"""

import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

import redis

from swarm.core.settings import Settings

if TYPE_CHECKING:
    # For type checking, Redis is generic
    RedisSyncClient = redis.Redis[Any]
else:
    # At runtime, Redis is not generic
    RedisSyncClient = redis.Redis

logger = logging.getLogger(__name__)

# Key prefix for affinity storage - separate from session metadata
SESSION_KEY_PREFIX = "browser:affinity:"


class BrowserSessionRouter:
    """
    Celery router that implements session affinity for browser tasks.

    Routes tasks to the worker that owns the browser session, or to
    the default queue for new sessions.

    Note: This router uses synchronous Redis calls to avoid blocking
    the Celery worker thread with async operations.
    """

    def __init__(self, redis_client: RedisSyncClient | None = None) -> None:
        """Initialize router with Redis client."""
        self._redis: RedisSyncClient | None = redis_client
        self._redis_url: str | None = None
        # Simple circuit breaker to avoid hot-path reconnect storms
        self._last_redis_error_at: float = 0.0
        self._redis_backoff_seconds: float = 5.0

    def _get_redis(self) -> RedisSyncClient | None:
        """Return a Redis client without blocking the hot path.

        - Do not ping on every call (avoids stalls).
        - Use a short backoff window before recreating a client after errors.
        """
        if self._redis is None:
            import time as _t

            # Respect backoff window to avoid repeated reconnect attempts
            if self._last_redis_error_at and (
                _t.monotonic() - self._last_redis_error_at < self._redis_backoff_seconds
            ):
                return None

            settings = Settings()
            if not settings.redis.url:
                self._last_redis_error_at = _t.monotonic()
                logger.error("Router Redis URL not configured")
                return None

            self._redis_url = settings.redis.url
            try:
                self._redis = redis.from_url(
                    self._redis_url,
                    decode_responses=True,
                    socket_connect_timeout=1,
                    socket_timeout=1,
                )
            except Exception as exc:
                logger.warning("Router Redis client creation failed: %r", exc)
                self._last_redis_error_at = _t.monotonic()
                self._redis = None
                return None

        return self._redis

    def _sanitize_worker_id(self, worker_id: str) -> str:
        """
        Sanitize worker ID for safe queue naming.

        Celery default hostnames look like 'worker@container-id'.
        The @ character can confuse queue declarations.
        """
        return worker_id.replace("@", "_")

    def _is_worker_healthy(self, worker_id: str, redis_client: RedisSyncClient) -> bool:
        """Check worker liveness strictly via WorkerLifecycle heartbeat.

        Healthy iff key "browser:worker:{worker_id}" exists.
        Fail-closed on errors to avoid routing to dead direct queues.
        """
        try:
            worker_key = f"browser:worker:{worker_id}"
            return bool(redis_client.exists(worker_key))
        except Exception as e:
            logger.error(f"Failed to check worker health: {e}")
            return False

    def route_for_task(
        self,
        task: str,
        args: tuple[Any, ...] | None = None,
        kwargs: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
        task_type: Any | None = None,
    ) -> dict[str, str] | None:
        """
        Route browser tasks based on session affinity.

        Args:
            task: Task name (e.g., "browser.goto")
            args: Task positional arguments
            kwargs: Task keyword arguments
            options: Celery routing options (optional)
            task_type: Task type (optional)

        Returns:
            Routing dict with queue name, or None for default routing
        """
        # Handle None args
        args = args or ()
        kwargs = kwargs or {}

        # Only route browser tasks
        if not task.startswith("browser."):
            return None

        # Skip cleanup tasks - they should go to default queue
        if task == "browser.cleanup":
            return {"queue": "browser"}

        # Extract session ID from kwargs (explicit session_id only)
        session_id = kwargs.get("session_id")
        if not session_id:
            # No session specified, use default routing
            logger.debug(f"No session_id kwarg on {task}; using default routing")
            return None

        logger.info(f"BrowserSessionRouter: Routing {task} with session_id={session_id}")

        # Look up session owner with fast synchronous call
        redis_client = self._get_redis()
        if redis_client is None:
            logger.warning("Router Redis unavailable; default routing for %s", task)
            return None

        try:
            # Build key efficiently with constant prefix - use string prefix since decode_responses=True
            session_key = "browser:affinity:" + session_id
            logger.info(f"BrowserSessionRouter: Looking up key={session_key}")

            # Single GET operation - no TTL refresh here
            owner = redis_client.get(session_key)
            logger.info(f"BrowserSessionRouter: Redis GET returned owner={owner}")

            if owner:
                # Route to worker's direct queue
                # Owner format is like "swarm_92d1d2a4afe3" but queue is "browser.direct.92d1d2a4afe3"
                # Extract the worker ID part after the underscore
                worker_id = str(owner)
                if "_" in worker_id:
                    worker_id = worker_id.split("_", 1)[1]  # Get part after first underscore

                # Check if worker is healthy before routing
                if self._is_worker_healthy(worker_id, redis_client):
                    direct_queue = f"browser.direct.{worker_id}"
                    logger.info(f"Routing task {task} for session {session_id} to {direct_queue}")
                    # Return full routing information including exchange and routing_key
                    return {
                        "queue": direct_queue,
                        "exchange": direct_queue,
                        "routing_key": direct_queue,
                    }
                else:
                    # Worker is dead, clear ownership and route to default
                    logger.warning(
                        f"Worker {worker_id} is not healthy, clearing session ownership",
                        extra={"session_id": session_id, "worker_id": worker_id},
                    )
                    try:
                        _ = redis_client.delete(session_key)
                    except Exception:
                        pass  # Best effort cleanup
                    return None
            else:
                # No owner found - new session or expired
                # Route to default queue and let the worker register itself
                logger.debug(f"No owner found for session {session_id}, using default routing")
                return None

        except Exception as exc:
            import time as _t
            logger.error(f"Error in session routing for {task}: {exc!r}")
            # Mark error time and fall back to default routing
            self._redis = None
            self._last_redis_error_at = _t.monotonic()
            return None


# Note on concurrency:
# - The router is called BEFORE task execution, so session lookups happen
#   before any worker claims the session
# - Workers register sessions AFTER receiving the task, avoiding most races
# - If two tasks for the same new session arrive simultaneously, both may
#   route to different workers - one will fail fast (acceptable for Phase 1)
# - TTL refresh happens in the worker when it actually uses the session
