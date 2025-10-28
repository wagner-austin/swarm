"""
Celery Router for Browser Session Affinity

Routes browser tasks to workers that own the session, enabling
deterministic task execution across multiple workers.
"""

import logging
import time
from typing import TYPE_CHECKING, Required, TypedDict

import redis

from swarm.core.logger_setup import bootstrap_logging
from swarm.core.settings import Settings
from swarm.infra.redis_protocols import RedisSyncProtocol, wrap_redis_sync

logger = logging.getLogger(__name__)

# Key prefix for affinity storage - separate from session metadata
SESSION_KEY_PREFIX = "browser:affinity:"


class Routing(TypedDict, total=False):
    """Typed routing map for Celery producer.

    Only 'queue' is required; 'exchange' and 'routing_key' are optional.
    """

    queue: Required[str]
    exchange: str
    routing_key: str


class BrowserSessionRouter:
    """
    Celery router that implements session affinity for browser tasks.

    Routes tasks to the worker that owns the browser session, or to
    the default queue for new sessions.

    Note: This router uses synchronous Redis calls to avoid blocking
    the Celery worker thread with async operations.
    """

    def __init__(self, redis_client: RedisSyncProtocol | None = None) -> None:
        """Initialize router with Redis client."""
        # Ensure logging context exists even during producer-side sends
        try:
            from swarm.utils.context_bootstrap import bootstrap_thread_log_context

            bootstrap_thread_log_context(service="celery-router")
        except Exception:
            # Logging may already be configured; proceed regardless
            pass
        self._redis: RedisSyncProtocol | None = redis_client
        self._redis_url: str | None = None
        # Simple circuit breaker to avoid hot-path reconnect storms
        self._last_redis_error_at: float = 0.0
        self._redis_backoff_seconds: float = 5.0

    def _get_redis(self) -> RedisSyncProtocol | None:
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
                client = redis.from_url(
                    self._redis_url,
                    decode_responses=True,
                    socket_connect_timeout=1,
                    socket_timeout=1,
                )
                self._redis = wrap_redis_sync(client)
            except Exception as exc:
                logger.warning("Router Redis client creation failed: %r", exc)
                self._last_redis_error_at = _t.monotonic()
                self._redis = None
                return None

        return self._redis

    def _is_worker_healthy(self, worker_id: str, redis_client: RedisSyncProtocol) -> bool:
        """Check worker liveness via Redis heartbeats (authoritative).

        Healthy iff heartbeat timestamp is fresh within the staleness window.
        """
        heartbeat_key = f"worker:heartbeat:browser:{worker_id}"
        attempts = 0
        while attempts < 3:
            attempts += 1
            try:
                ts_str = redis_client.hget(heartbeat_key, "timestamp")
                if not ts_str:
                    return False
                try:
                    ts = float(ts_str)
                except Exception:
                    return False
                now = time.time()
                stale_window = 90.0
                return (now - ts) <= stale_window
            except Exception as e:
                # Retry on transient timeouts
                if "Timeout" in str(e) and attempts < 3:
                    time.sleep(0.02)
                    continue
                logger.error(f"Failed to check worker health: {e}")
                return False
        return False

    def route_for_task(
        self,
        task: str,
        args: tuple[object, ...] | None = None,
        kwargs: dict[str, object] | None = None,
        options: dict[str, object] | None = None,
        task_type: object | None = None,
    ) -> Routing | None:
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

        # Cleanup tasks: prefer routing to the owner direct queue when known/healthy
        if task == "browser.cleanup":
            sid_obj2 = kwargs.get("session_id")
            if isinstance(sid_obj2, str):
                redis_client2 = self._get_redis()
                if redis_client2 is not None:
                    try:
                        session_key2 = "browser:affinity:" + sid_obj2
                        worker_id2 = redis_client2.hget(session_key2, "worker_id")
                        direct_queue2 = redis_client2.hget(session_key2, "direct_queue")
                        if worker_id2 and direct_queue2:
                            if self._is_worker_healthy(worker_id2, redis_client2):
                                dq2 = direct_queue2
                                return Routing(queue=dq2, exchange=dq2, routing_key=dq2)
                    except Exception as exc:
                        logger.warning("Router: cleanup routing lookup failed: %r", exc)
            # Fallback to base queue
            return Routing(queue="browser")

        # Extract session ID from kwargs (explicit session_id only)
        sid_obj = kwargs.get("session_id")
        if not isinstance(sid_obj, str):
            # No session specified, use default routing
            logger.debug(f"No session_id kwarg on {task}; using default routing")
            return None

        logger.info(f"BrowserSessionRouter: Routing {task} with session_id={sid_obj}")

        # Look up session affinity via hash (authoritative contract)
        redis_client = self._get_redis()
        if redis_client is None:
            logger.warning("Router Redis unavailable; default routing for %s", task)
            return None

        try:
            session_key = "browser:affinity:" + sid_obj
            logger.info(f"BrowserSessionRouter: Looking up key={session_key}")

            # Authoritative fields written by the session registry (with tiny retry on timeout)
            attempts2 = 0
            worker_id = None
            direct_queue = None
            while attempts2 < 3:
                attempts2 += 1
                try:
                    worker_id = redis_client.hget(session_key, "worker_id")
                    direct_queue = redis_client.hget(session_key, "direct_queue")
                    break
                except Exception as he:
                    if "Timeout" in str(he) and attempts2 < 3:
                        time.sleep(0.02)
                        continue
                    raise
            logger.info(
                f"BrowserSessionRouter: Found worker_id={worker_id}, direct_queue={direct_queue}"
            )

            if worker_id and direct_queue:
                if self._is_worker_healthy(worker_id, redis_client):
                    dq = direct_queue
                    logger.info(f"Routing task {task} for session {sid_obj} to {dq}")
                    return Routing(queue=dq, exchange=dq, routing_key=dq)
                # Worker unhealthy: clear affinity and fall back to default
                logger.warning(
                    f"Worker {worker_id} is not healthy, clearing session affinity",
                    extra={"session_id": sid_obj, "worker_id": worker_id},
                )
                try:
                    _ = redis_client.delete(session_key)
                except Exception:
                    pass
                return None

            # No affinity found
            logger.info(
                f"BrowserSessionRouter: No affinity for {sid_obj}, returning None for default routing"
            )
            return None

        except Exception as exc:
            import time as _t

            logger.error(
                f"BrowserSessionRouter: Exception during routing for {task}: {exc!r}", exc_info=True
            )
            # Mark error time and fall back to default routing.
            # Only drop the cached client if we created it ourselves; if an
            # external client was injected, keep it so callers can retry.
            if self._redis_url:
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
# NOTE: The Routing TypedDict is defined above the class to avoid
# undefined-name checks in tools that don't postpone annotation evaluation.
