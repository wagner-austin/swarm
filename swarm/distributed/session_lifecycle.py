"""
Session lifecycle management with automatic TTL-based cleanup.

Design goals:
- No use of typing.Any or casts
- Deterministic cleanup of leaked browser engines
- Background cleanup loop on a dedicated event loop thread
- Async-friendly public API for tasks to await (register/heartbeat/unregister)
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional, TypedDict

logger = logging.getLogger(__name__)


@dataclass
class SessionMetadata:
    session_id: str
    worker_id: str
    created_at: float
    last_activity: float
    ttl_seconds: float


class SessionLifecycleManager:
    """Manages session lifecycle with automatic TTL-based cleanup.

    The manager owns a dedicated background event loop running on a thread.
    All public async methods proxy to that loop using run_coroutine_threadsafe
    to avoid interfering with caller loops (e.g., Celery worker thread loops).
    """

    def __init__(self, cleanup_interval: float = 60.0) -> None:
        self._cleanup_interval: float = cleanup_interval
        self._sessions: dict[str, SessionMetadata] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._loop_ready: threading.Event = threading.Event()
        self._stop_event: threading.Event = threading.Event()
        self._cleanup_task: asyncio.Task[None] | None = None
        self._lock: asyncio.Lock | None = None
        self._stop_async: asyncio.Event | None = None
        # Metrics (typed wrappers, optional dependency behind a typed facade)
        from swarm.metrics.typed import Counter, Gauge, make_counter, make_gauge

        self._m_active: Gauge = make_gauge(
            "browser_sessions_active", "Current active browser sessions per worker"
        )
        self._m_created_total: Counter = make_counter(
            "browser_sessions_created_total", "Total browser sessions created per worker"
        )
        self._m_cleaned_total: Counter = make_counter(
            "browser_sessions_cleaned_total", "Total browser sessions cleaned per worker"
        )
        self._m_expired_total: Counter = make_counter(
            "browser_sessions_expired_total", "Total browser sessions expired by TTL per worker"
        )

    # -----------------------
    # Lifecycle (synchronous)
    # -----------------------
    def start(self) -> None:
        """Start the lifecycle manager loop thread (idempotent)."""
        if self._loop_thread and self._loop and self._loop.is_running():
            return

        self._stop_event.clear()
        self._loop_ready.clear()
        self._loop_thread = threading.Thread(
            target=self._loop_main,
            name="SessionLifecycleLoop",
            daemon=False,
        )
        self._loop_thread.start()
        if not self._loop_ready.wait(timeout=5.0):
            raise RuntimeError("Timed out starting SessionLifecycleManager loop thread")
        logger.info("SessionLifecycleManager started")

    def stop(self) -> None:
        """Stop the lifecycle loop and cleanup all sessions synchronously."""
        loop = self._loop
        if loop is None:
            return

        # Request full cleanup on the manager loop then stop it
        async def _shutdown() -> None:
            # Signal cleanup loop to exit promptly
            if self._stop_async is not None:
                self._stop_async.set()
            await self._cleanup_all_sessions()

        try:
            fut = asyncio.run_coroutine_threadsafe(_shutdown(), loop)
            fut.result(timeout=30)
        except Exception as exc:
            logger.warning(f"Error awaiting lifecycle shutdown: {exc}")
            try:
                # Centralized error service alert (best-effort)
                from swarm.core import alerts

                alerts.alert(f"Lifecycle shutdown error: {exc}")
            except Exception:
                pass

        try:
            self._stop_event.set()
            loop.call_soon_threadsafe(loop.stop)
        except Exception:
            pass
        if self._loop_thread and threading.current_thread() is not self._loop_thread:
            try:
                self._loop_thread.join(timeout=5.0)
            except Exception:
                pass
        self._loop_thread = None
        self._loop = None
        self._cleanup_task = None
        self._loop_ready.clear()
        logger.info("SessionLifecycleManager stopped")

    def _loop_main(self) -> None:
        """Background thread main: run a dedicated asyncio loop forever."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._loop_ready.set()
        try:
            # Initialize async primitives on this loop
            self._lock = asyncio.Lock()
            self._stop_async = asyncio.Event()
            # Start cleanup task
            self._cleanup_task = loop.create_task(self._cleanup_loop())
            loop.run_forever()
        finally:
            # Drain tasks cooperatively, then shutdown async generators
            pending = {t for t in asyncio.all_tasks(loop) if not t.done()}
            if pending:

                async def _drain() -> None:
                    await asyncio.gather(*pending, return_exceptions=True)

                loop.run_until_complete(_drain())
            if hasattr(loop, "shutdown_asyncgens"):
                loop.run_until_complete(loop.shutdown_asyncgens())
            try:
                loop.close()
            except Exception:
                pass

    # --------------
    # Public API (awaitable, proxies to internal loop)
    # --------------
    async def register_session(
        self, session_id: str, worker_id: str, ttl_seconds: float = 3600
    ) -> None:
        loop = self._ensure_loop()

        async def _inner() -> None:
            assert self._lock is not None
            async with self._lock:
                self._sessions[session_id] = SessionMetadata(
                    session_id=session_id,
                    worker_id=worker_id,
                    created_at=time.time(),
                    last_activity=time.time(),
                    ttl_seconds=ttl_seconds,
                )
            # Update metrics while holding lock for consistent count
            try:
                self._m_created_total.labels(worker_id=worker_id).inc()
                count = sum(1 for s in self._sessions.values() if s.worker_id == worker_id)
                self._m_active.labels(worker_id=worker_id).set(float(count))
            except Exception:
                # Metrics must not interfere with lifecycle logic
                pass
            logger.info(
                f"Registered session {session_id} with TTL {ttl_seconds}s (owner={worker_id})"
            )

        fut = asyncio.run_coroutine_threadsafe(_inner(), loop)
        await asyncio.wrap_future(fut)

    async def heartbeat_session(self, session_id: str) -> None:
        loop = self._ensure_loop()

        async def _inner() -> None:
            assert self._lock is not None
            async with self._lock:
                meta = self._sessions.get(session_id)
                if meta is not None:
                    meta.last_activity = time.time()

        fut = asyncio.run_coroutine_threadsafe(_inner(), loop)
        await asyncio.wrap_future(fut)

    async def unregister_session(self, session_id: str) -> None:
        loop = self._ensure_loop()

        async def _inner() -> None:
            # Drop metadata first and then cleanup attached engine/affinity
            assert self._lock is not None
            async with self._lock:
                meta = self._sessions.pop(session_id, None)
            await self._cleanup_session(session_id)
            logger.info(f"Unregistered session {session_id}")
            # Metrics: update cleaned counter and active gauge for the owning worker
            try:
                if meta is not None:
                    self._m_cleaned_total.labels(worker_id=meta.worker_id).inc()
                    assert self._lock is not None
                    async with self._lock:
                        count = sum(
                            1 for s in self._sessions.values() if s.worker_id == meta.worker_id
                        )
                    self._m_active.labels(worker_id=meta.worker_id).set(float(count))
            except Exception:
                pass

        fut = asyncio.run_coroutine_threadsafe(_inner(), loop)
        await asyncio.wrap_future(fut)

    # -----------------
    # Internal coroutines (run on manager loop)
    # -----------------
    async def _cleanup_loop(self) -> None:
        """Background loop that periodically cleans up expired sessions.

        Uses an asyncio.Event to allow prompt shutdown without relying on task
        cancellation. The event is set from the synchronous stop() method.
        """
        assert self._stop_async is not None
        while True:
            try:
                # Wait for stop, or time out to run periodic cleanup
                await asyncio.wait_for(self._stop_async.wait(), timeout=self._cleanup_interval)
                break
            except TimeoutError:
                try:
                    await self._cleanup_expired_sessions()
                except Exception as exc:
                    logger.error(f"Error in lifecycle cleanup loop: {exc}", exc_info=True)
                    try:
                        from swarm.core import alerts

                        alerts.alert(f"Lifecycle cleanup loop error: {exc}")
                    except Exception:
                        pass

    async def _cleanup_expired_sessions(self) -> None:
        now = time.time()
        expired: list[tuple[str, str]] = []

        assert self._lock is not None
        async with self._lock:
            for sid, meta in self._sessions.items():
                age = now - meta.last_activity
                if age > meta.ttl_seconds:
                    expired.append((sid, meta.worker_id))

        for sid, owner in expired:
            try:
                await self.unregister_session(sid)
                try:
                    self._m_expired_total.labels(worker_id=owner).inc()
                except Exception:
                    pass
            except Exception as exc:
                logger.warning(f"Error unregistering expired session {sid}: {exc}")

    # -----------------
    # Metrics snapshot (strict TypedDict)
    # -----------------
    class _WorkerSessions(TypedDict):
        worker_id: str
        active_sessions: int

    class LifecycleMetricsSnapshot(TypedDict):
        total_active: int
        workers: list[SessionLifecycleManager._WorkerSessions]

    async def get_metrics_snapshot(self) -> SessionLifecycleManager.LifecycleMetricsSnapshot:
        assert self._lock is not None
        async with self._lock:
            counts: dict[str, int] = {}
            for meta in self._sessions.values():
                counts[meta.worker_id] = counts.get(meta.worker_id, 0) + 1
        workers_list: list[SessionLifecycleManager._WorkerSessions] = [
            {"worker_id": wid, "active_sessions": cnt} for wid, cnt in counts.items()
        ]
        total = sum(counts.values())
        return {"total_active": total, "workers": workers_list}

    async def _cleanup_all_sessions(self) -> None:
        assert self._lock is not None
        async with self._lock:
            session_ids = list(self._sessions.keys())
        for sid in session_ids:
            try:
                await self._cleanup_session(sid)
            except Exception as exc:
                logger.warning(f"Error cleaning session {sid}: {exc}")
        # Clear after attempting cleanup
        async with self._lock:
            self._sessions.clear()

    async def _cleanup_session(self, session_id: str) -> None:
        """Cleanup browser engine and clear affinity for a session."""
        # Import inside to avoid import cycles
        from swarm.browser.engine import BrowserEngine
        from swarm.distributed.session_registry import SessionRegistry
        from swarm.tasks import browser as browser_tasks
        from swarm.utils.worker_identity import canonical_worker_id

        # Remove engine from registry and stop it
        engine: object | None
        with browser_tasks._engines_lock:
            engine = browser_tasks._engines.pop(session_id, None)

        if isinstance(engine, BrowserEngine):
            try:
                await engine.stop(graceful=True)
                logger.info(f"Cleaned up engine for session {session_id}")
            except Exception as exc:
                logger.error(f"Error stopping engine for {session_id}: {exc}")
                try:
                    from swarm.core import alerts

                    alerts.alert(f"Engine stop error for session {session_id}: {exc}")
                except Exception:
                    pass

        # Clear affinity mapping in Redis (best effort)
        try:
            registry = SessionRegistry()
            await registry.clear_owner(session_id)
        except Exception as exc:
            logger.debug(f"Error clearing affinity for {session_id}: {exc}")

        # Remove from worker lifecycle set if possible
        try:
            # We don't know the exact worker owner here; it's best effort via affinity or local hostname
            # For local process, remove session from local lifecycle (if recorded)
            from swarm.distributed.worker_lifecycle import WorkerLifecycle

            wid = canonical_worker_id(None)
            WorkerLifecycle(wid).remove_session(session_id)
        except Exception:
            # Best effort only
            pass

    # --------------
    # Helpers
    # --------------
    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        loop = self._loop
        if loop is None or not loop.is_running():
            # Attempt auto-start to avoid surprises if worker_ready did not fire yet
            self.start()
            loop = self._loop
        if loop is None or not loop.is_running():
            raise RuntimeError("SessionLifecycleManager loop not running")
        return loop


# Module-level singleton for easy importing in tasks and signals
lifecycle_manager = SessionLifecycleManager()
