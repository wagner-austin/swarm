"""
Browser automation tasks for Celery.

Production-grade task-scoped browser automation for the AI Task Assistant.
Each task gets its own browser session that auto-cleans up on completion.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import tempfile
import threading
import uuid
import weakref
from contextlib import suppress
from functools import wraps
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Literal, Protocol, TypedDict, TypeGuard

import redis.asyncio as redis_asyncio
from billiard.einfo import ExceptionInfo
from celery import Celery, group, signals
from celery.canvas import Signature

from swarm.browser.engine import BrowserEngine
from swarm.browser.types import (
    BrowserEngineStatus,
    CleanupTaskResponse,
    ClickTaskResponse,
    FillTaskResponse,
    GotoTaskResponse,
    ScrapeDataItem,
    ScrapeDataResponse,
    ScreenshotTaskResponse,
    StartTaskResponse,
    StatusTaskResponse,
    UploadTaskResponse,
    WaitForTaskResponse,
)
from swarm.celery_app import app
from swarm.core.settings import Settings
from swarm.distributed.worker_lifecycle import WorkerLifecycle
from swarm.infra.redis_keys import session_state_key
from swarm.infra.redis_protocols import RedisAsyncProtocol, wrap_redis_async
from swarm.tasks._base import SwarmTask
from swarm.utils.worker_identity import canonical_worker_id, direct_queue_name

"""Task protocol for functions that only need Celery's request.id."""


class _RequestProto(Protocol):
    id: str


class _TaskProto(Protocol):
    request: _RequestProto


TaskType = _TaskProto

# Type for the creating sentinel
_CreatingSentinel = Literal["__creating__"]

logger = logging.getLogger(__name__)


def typed_task(
    *,
    base: type | None = None,
    bind: bool | None = None,
    name: str | None = None,
) -> Callable[[Callable[..., object]], object]:
    """
    Register a function as a Celery task and transparently bridge async
    coroutines to the (threads) worker pool using thread-safe execution.

    Args:
        base: Base task class (defaults to SwarmTask)
        bind: Whether to bind the task instance as first argument
        name: Explicit task name
    """

    def decorator(fn: Callable[..., object]) -> object:
        if asyncio.iscoroutinefunction(fn):

            @wraps(fn)
            def sync_wrapper(self: object, *args: object, **kwargs: object) -> object:
                # Get stable thread-local event loop
                if isinstance(self, SwarmTask):
                    loop = self.get_loop()
                    # Run the coroutine to completion on this thread's loop
                    return loop.run_until_complete(fn(self, *args, **kwargs))
                else:
                    # Fallback for non-SwarmTask instances
                    return asyncio.run(fn(self, *args, **kwargs))

            # Ensure base=SwarmTask and call Celery with explicit keywords to satisfy typing
            # Let mypy infer type to satisfy Celery's TypeVar bound
            base_cls: type = base if base is not None else SwarmTask

            # Narrow optional types before passing to Celery's strict API
            dec: Callable[[Callable[..., object]], object]
            if bind is not None and name is not None:
                # Both bind and name are provided
                dec = app.task(base=base_cls, bind=bind, name=name)  # narrow to our callable shape
            elif bind is not None:
                # Only bind is provided (name is None)
                dec = app.task(base=base_cls, bind=bind)
            elif name is not None:
                # Only name is provided (bind is None)
                dec = app.task(base=base_cls, name=name)
            else:
                # Neither bind nor name provided
                dec = app.task(base=base_cls)
            return dec(sync_wrapper)

        # Plain sync function - same pattern
        # Let mypy infer type to satisfy Celery's TypeVar bound
        base_cls2: type = base if base is not None else SwarmTask

        # Narrow optional types before passing to Celery's strict API
        dec2: Callable[[Callable[..., object]], object]
        if bind is not None and name is not None:
            # Both bind and name are provided
            dec2 = app.task(base=base_cls2, bind=bind, name=name)
        elif bind is not None:
            # Only bind is provided (name is None)
            dec2 = app.task(base=base_cls2, bind=bind)
        elif name is not None:
            # Only name is provided (bind is None)
            dec2 = app.task(base=base_cls2, name=name)
        else:
            # Neither bind nor name provided
            dec2 = app.task(base=base_cls2)
        return dec2(fn)

    return decorator


# Module-level storage for browser engines (global with thread safety)
# Use a regular dict with threading lock to share engines across threads
# Each engine still runs on its own event loop, but can be accessed from any thread
# via the _run_on_engine_loop proxy method in BrowserEngine
_CREATING_SENTINEL: _CreatingSentinel = "__creating__"
_engines: dict[str, BrowserEngine | _CreatingSentinel] = {}
_engines_lock = threading.Lock()

# Weak reference dictionary to store Redis clients per event loop
# This ensures clients are garbage collected when the loop is destroyed
_loop_clients: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, RedisAsyncProtocol] = (
    weakref.WeakKeyDictionary()
)


# Action schemas for scrape_data
class ClickAction(TypedDict):
    type: Literal["click"]
    selector: str


class FillAction(TypedDict):
    type: Literal["fill"]
    selector: str
    text: str


class WaitAction(TypedDict, total=False):
    type: Literal["wait"]
    selector: str
    state: Literal["visible", "hidden", "attached", "detached"]


class ScreenshotAction(TypedDict):
    type: Literal["screenshot"]


Action = ClickAction | FillAction | WaitAction | ScreenshotAction


def is_click_action(a: Action) -> TypeGuard[ClickAction]:
    return a.get("type") == "click" and "selector" in a


def is_fill_action(a: Action) -> TypeGuard[FillAction]:
    return a.get("type") == "fill" and "selector" in a and "text" in a


def is_wait_action(a: Action) -> TypeGuard[WaitAction]:
    return a.get("type") == "wait" and "selector" in a


def is_screenshot_action(a: Action) -> TypeGuard[ScreenshotAction]:
    return a.get("type") == "screenshot"


def action_as_plain(a: Action) -> dict[str, object]:
    # Safely convert the TypedDict union to a plain dict for result payloads
    return {k: v for k, v in a.items()}


class BrowserTask(SwarmTask[..., object]):
    """Base task for browser operations with session management."""

    async def get_redis(self) -> RedisAsyncProtocol:
        """Get or create Redis client for the current event loop."""
        loop = asyncio.get_running_loop()
        client = _loop_clients.get(loop)

        if client is None:
            settings = Settings()
            if not settings.redis.url:
                raise ValueError("Redis URL not configured")

            # Create client with limited connection pool for thread pool workers
            # Each thread gets its own loop and client, so we don't need many connections
            inner = redis_asyncio.from_url(
                settings.redis.url,
                max_connections=2,  # Limit connections per event loop
            )
            client_wrapped = wrap_redis_async(inner)
            _loop_clients[loop] = client_wrapped
            logger.debug(f"Created new Redis client for event loop {id(loop)}")

        # Return the protocol-typed client from cache
        proto_client = _loop_clients.get(loop)
        assert proto_client is not None
        return proto_client

    async def get_or_create_engine(self, session_id: str) -> BrowserEngine:
        """Return the BrowserEngine for session_id, creating it once in a thread-safe way."""
        thread_id = threading.current_thread().ident
        worker_id = canonical_worker_id(getattr(self.request, "hostname", None))
        task_id = getattr(self.request, "id", None)

        logger.info(
            f"get_or_create_engine called: session_id={session_id}, "
            f"worker_id={worker_id}, thread_id={thread_id}, task_id={task_id}"
        )

        # Fast path: someone already created it
        with _engines_lock:
            existing = _engines.get(session_id)
            logger.info(
                f"Lock acquired: existing type={type(existing).__name__ if existing else 'None'}, "
                f"total_engines={sum(1 for v in _engines.values() if isinstance(v, BrowserEngine))}"
            )

            if isinstance(existing, BrowserEngine):
                logger.info(
                    f"Session {session_id} found existing engine on worker {worker_id}, thread {thread_id}"
                )
                return existing
            if existing is _CREATING_SENTINEL:
                # Another thread is creating; fall through to wait loop
                logger.warning(
                    f"Found CREATING_SENTINEL for {session_id}, entering wait loop (worker={worker_id})"
                )
                pass
            else:
                # Enforce per-worker engine capacity before creating a new one
                try:
                    worker_id = canonical_worker_id(getattr(self.request, "hostname", None))
                    max_allowed = WorkerLifecycle(worker_id).max_sessions
                except Exception:
                    # Fallback if lifecycle not available
                    worker_id = canonical_worker_id(getattr(self.request, "hostname", None))
                    max_allowed = 10
                engine_count = sum(1 for v in _engines.values() if isinstance(v, BrowserEngine))
                if engine_count >= max_allowed:
                    active_sessions = [
                        sid for sid, v in _engines.items() if isinstance(v, BrowserEngine)
                    ]
                    logger.error(
                        "Engine limit reached (%s/%s). Active sessions: %s",
                        engine_count,
                        max_allowed,
                        active_sessions,
                    )
                    raise RuntimeError(
                        f"Worker at capacity ({engine_count} engines). Sessions may have leaked."
                    )
                # We'll create it - claim creation slot
                _engines[session_id] = _CREATING_SENTINEL

        if existing is _CREATING_SENTINEL:
            # Spin-wait until engine appears
            while True:
                await asyncio.sleep(0.05)  # 50ms to reduce CPU noise
                with _engines_lock:
                    engine = _engines.get(session_id)
                    if isinstance(engine, BrowserEngine):
                        logger.info(f"Engine for {session_id} created by another thread")
                        return engine
        else:
            # We're the creator
            try:
                logger.info(f"Creating browser engine for session {session_id}")
                engine = BrowserEngine(headless=True, proxy=None, timeout_ms=60000)
                await engine.start()
                with _engines_lock:
                    _engines[session_id] = engine
                    engine_count = sum(1 for v in _engines.values() if isinstance(v, BrowserEngine))
                    logger.info(
                        f"Stored engine for session {session_id} (total engines: {engine_count})"
                    )

                # Register session with affinity registry
                from swarm.distributed.session_registry import SessionRegistry

                try:
                    registry = SessionRegistry()
                    worker_id = canonical_worker_id(getattr(self.request, "hostname", None))
                    logger.info(
                        f"Registering affinity for session {session_id} to worker {worker_id}"
                    )
                    success = await registry.set_owner(session_id, worker_id)
                    logger.info(f"Registry.set_owner returned: {success}")
                    if success:
                        logger.info(f"Successfully registered affinity for session {session_id}")
                        # Track session ownership for deterministic cleanup on shutdown
                        try:
                            WorkerLifecycle(worker_id).add_session(session_id)
                        except Exception as le:
                            logger.warning(f"Failed to record session ownership in lifecycle: {le}")
                    else:
                        logger.error(f"Failed to register affinity for session {session_id}")
                except Exception as e:
                    logger.error(f"Error registering session affinity: {e}", exc_info=True)

                # Register with lifecycle manager for TTL-based cleanup
                try:
                    from swarm.distributed.session_lifecycle import lifecycle_manager

                    await lifecycle_manager.register_session(
                        session_id=session_id,
                        worker_id=worker_id,
                        ttl_seconds=3600,
                    )
                except Exception as le:
                    logger.warning(f"Failed to register session with lifecycle manager: {le}")

                return engine
            except Exception as e:
                # Creation failed - remove sentinel
                with _engines_lock:
                    if _engines.get(session_id) is _CREATING_SENTINEL:
                        del _engines[session_id]
                logger.error(f"Failed to create engine for {session_id}: {e}")
                raise

    async def auto_cleanup_session(self, session_id: str) -> None:
        """Cleanup session via lifecycle manager, called from finally blocks.

        Centralizes cleanup logic to prevent drift across tasks.
        """
        from swarm.distributed.session_lifecycle import lifecycle_manager

        try:
            await lifecycle_manager.unregister_session(session_id)
        except Exception as e:
            logger.error(f"Failed to cleanup session {session_id}: {e}")

    def on_failure(
        self,
        exc: Exception,
        task_id: str,
        args: tuple[object, ...],
        kwargs: dict[str, object],
        einfo: ExceptionInfo,
    ) -> None:
        """Clean up on task failure."""
        # Don't schedule cleanup here - rely on the finally block in each task
        # to avoid double cleanup. The finally block will run even on failure.
        super().on_failure(exc, task_id, args, kwargs, einfo)


@typed_task(base=BrowserTask, bind=True, name="browser.goto")
async def goto(
    self: BrowserTask, url: str, session_id: str | None = None, auto_cleanup: bool = False
) -> GotoTaskResponse:
    """Navigate to a URL within a task's browser session.

    Args:
        url: The URL to navigate to
        session_id: Session ID for session management (defaults to current task)
        auto_cleanup: If True, cleanup session after this task completes

    Returns:
        Dict with success status and navigation details
    """
    session_id = self.resolve_session_id(session_id)

    try:
        engine = await self.get_or_create_engine(session_id)
        # Heartbeat to extend session TTL
        try:
            from swarm.distributed.session_lifecycle import lifecycle_manager

            await lifecycle_manager.heartbeat_session(session_id)
        except Exception as hb_exc:
            logger.warning(
                "Lifecycle heartbeat failed for session %s during goto: %r",
                session_id,
                hb_exc,
                exc_info=True,
            )
        await engine.goto(url)

        # Update session metadata with current URL
        redis = await self.get_redis()
        await redis.hset(session_state_key(session_id), "url", url)

        return {"success": True, "session_id": session_id, "url": url}
    finally:
        if auto_cleanup:
            await self.auto_cleanup_session(session_id)


@typed_task(base=BrowserTask, bind=True, name="browser.click")
async def click(
    self: BrowserTask,
    selector: str,
    session_id: str | None = None,
    no_wait_after: bool = False,
    auto_cleanup: bool = False,
) -> ClickTaskResponse:
    """Click an element within a task's browser session.

    Args:
        selector: CSS selector for the element
        session_id: Session ID for session management (defaults to current task)
        no_wait_after: If True, don't wait for navigation after click
        auto_cleanup: If True, cleanup session after this task completes

    Returns:
        Dict with click result
    """
    session_id = self.resolve_session_id(session_id)

    try:
        engine = await self.get_or_create_engine(session_id)
        try:
            from swarm.distributed.session_lifecycle import lifecycle_manager

            await lifecycle_manager.heartbeat_session(session_id)
        except Exception as hb_exc:
            logger.warning(
                "Lifecycle heartbeat failed for session %s during click: %r",
                session_id,
                hb_exc,
                exc_info=True,
            )
        await engine.click(selector, no_wait_after=no_wait_after)

        return {"success": True, "session_id": session_id, "selector": selector}
    finally:
        if auto_cleanup:
            await self.auto_cleanup_session(session_id)


@typed_task(base=BrowserTask, bind=True, name="browser.fill")
async def fill(
    self: BrowserTask,
    selector: str,
    text: str,
    session_id: str | None = None,
    auto_cleanup: bool = False,
) -> FillTaskResponse:
    """Fill a form field within a task's browser session.

    Args:
        selector: CSS selector for the field
        text: Text to fill
        session_id: Session ID for session management (defaults to current task)
        auto_cleanup: If True, cleanup session after this task completes

    Returns:
        Dict with fill result
    """
    session_id = self.resolve_session_id(session_id)

    try:
        engine = await self.get_or_create_engine(session_id)
        try:
            from swarm.distributed.session_lifecycle import lifecycle_manager

            await lifecycle_manager.heartbeat_session(session_id)
        except Exception as hb_exc:
            logger.warning(
                "Lifecycle heartbeat failed for session %s during fill: %r",
                session_id,
                hb_exc,
                exc_info=True,
            )
        await engine.fill(selector, text)

        return {"success": True, "session_id": session_id, "selector": selector, "text": text}
    finally:
        if auto_cleanup:
            await self.auto_cleanup_session(session_id)


@typed_task(base=BrowserTask, bind=True, name="browser.upload")
async def upload(
    self: BrowserTask,
    selector: str,
    file_path: str,
    session_id: str | None = None,
    auto_cleanup: bool = False,
) -> UploadTaskResponse:
    """Upload a file to a form field.

    Args:
        selector: CSS selector for the file input
        file_path: Path to the file to upload
        session_id: Session ID for session management (defaults to current task)
        auto_cleanup: If True, cleanup session after this task completes

    Returns:
        Dict with upload result
    """
    session_id = self.resolve_session_id(session_id)

    try:
        engine = await self.get_or_create_engine(session_id)
        try:
            from swarm.distributed.session_lifecycle import lifecycle_manager

            await lifecycle_manager.heartbeat_session(session_id)
        except Exception as hb_exc:
            logger.warning(
                "Lifecycle heartbeat failed for session %s during upload: %r",
                session_id,
                hb_exc,
                exc_info=True,
            )
        await engine.upload(selector, Path(file_path))

        return {
            "success": True,
            "session_id": session_id,
            "selector": selector,
            "file_path": file_path,
        }
    finally:
        if auto_cleanup:
            await self.auto_cleanup_session(session_id)


@typed_task(base=BrowserTask, bind=True, name="browser.wait_for")
async def wait_for(
    self: BrowserTask,
    selector: str,
    state: Literal["visible", "hidden", "attached", "detached"] = "visible",
    session_id: str | None = None,
    auto_cleanup: bool = False,
) -> WaitForTaskResponse:
    """Wait for an element to reach a specific state.

    Args:
        selector: CSS selector to wait for
        state: State to wait for
        session_id: Session ID for session management (defaults to current task)
        auto_cleanup: If True, cleanup session after this task completes

    Returns:
        Dict with wait result
    """
    session_id = self.resolve_session_id(session_id)

    try:
        engine = await self.get_or_create_engine(session_id)
        try:
            from swarm.distributed.session_lifecycle import lifecycle_manager

            await lifecycle_manager.heartbeat_session(session_id)
        except Exception as hb_exc:
            logger.warning(
                "Lifecycle heartbeat failed for session %s during wait_for: %r",
                session_id,
                hb_exc,
                exc_info=True,
            )
        await engine.wait_for(selector, state)

        return {"success": True, "session_id": session_id, "selector": selector, "state": state}
    finally:
        if auto_cleanup:
            await self.auto_cleanup_session(session_id)


@typed_task(base=BrowserTask, bind=True, name="browser.screenshot")
async def screenshot(
    self: BrowserTask, session_id: str | None = None, auto_cleanup: bool = False
) -> ScreenshotTaskResponse:
    """Take a screenshot within a task's browser session.

    Args:
        session_id: Session ID for session management (defaults to current task)
        auto_cleanup: If True, cleanup session after screenshot completes

    Returns:
        Dict with base64 encoded screenshot
    """
    session_id = self.resolve_session_id(session_id)
    temp_path = os.path.join(tempfile.gettempdir(), f"screenshot_{session_id}_{os.getpid()}.png")

    try:
        engine = await self.get_or_create_engine(session_id)
        try:
            from swarm.distributed.session_lifecycle import lifecycle_manager

            await lifecycle_manager.heartbeat_session(session_id)
        except Exception as hb_exc:
            logger.warning(
                "Lifecycle heartbeat failed for session %s during screenshot: %r",
                session_id,
                hb_exc,
                exc_info=True,
            )

        await engine.screenshot(temp_path)

        with open(temp_path, "rb") as f:
            image_data = f.read()

        return {
            "success": True,
            "session_id": session_id,
            "data": base64.b64encode(image_data).decode("utf-8"),
        }
    finally:
        # Always cleanup temp file
        if os.path.exists(temp_path):
            os.unlink(temp_path)

        # Optionally cleanup session
        if auto_cleanup:
            await self.auto_cleanup_session(session_id)


@typed_task(base=BrowserTask, bind=True, name="browser.status")
async def status(
    self: BrowserTask, session_id: str | None = None, auto_cleanup: bool = False
) -> StatusTaskResponse:
    """Get status of a browser session.

    Args:
        session_id: Session ID for session management (defaults to current task)
        auto_cleanup: If True, cleanup session after getting status

    Returns:
        Dict with session status
    """
    session_id = self.resolve_session_id(session_id)

    try:
        # Heartbeat even if engine not present to keep active sessions alive
        try:
            from swarm.distributed.session_lifecycle import lifecycle_manager

            await lifecycle_manager.heartbeat_session(session_id)
        except Exception as hb_exc:
            logger.warning(
                "Lifecycle heartbeat failed for session %s during status: %r",
                session_id,
                hb_exc,
                exc_info=True,
            )

        # Check if engine exists in global registry
        with _engines_lock:
            engine = _engines.get(session_id)

        if isinstance(engine, BrowserEngine):
            engine_status: BrowserEngineStatus = await engine.status()
            # Ensure session_id is present for UI rendering (/web status)
            try:
                engine_status["session_id"] = str(session_id)
            except Exception:
                # Best-effort; if session_id is not serializable, omit it
                pass
            return {"success": True, "data": engine_status}
        else:
            # No active engine for this session: treat as not_found to avoid
            # rendering stale URL or unknown worker details.
            # so callers don't render confusing partial details.
            data_nf: BrowserEngineStatus = {
                "session_id": str(session_id),
                "status": "not_found",
                "browser_active": False,
                "page_active": False,
                "sessions": 0,
                "worker_id": "unknown",
                "url": None,
                "uptime": 0.0,
            }
            return {"success": True, "data": data_nf}
    finally:
        if auto_cleanup:
            await self.auto_cleanup_session(session_id)


@typed_task(base=BrowserTask, bind=True, name="browser.start")
async def start(
    self: BrowserTask, session_id: str | None = None, auto_cleanup: bool = False
) -> StartTaskResponse:
    """Explicitly start a browser session for a task.

    Args:
        session_id: Session ID for session management (defaults to current task)
        auto_cleanup: If True, cleanup session after starting

    Returns:
        Dict with session start result
    """
    session_id = self.resolve_session_id(session_id)

    try:
        engine = await self.get_or_create_engine(session_id)
        # Resume last known URL for this session if present (best-effort)
        try:
            redis = await self.get_redis()
            sdata = await redis.hgetall(session_state_key(session_id))
            last_url = sdata.get("url") if isinstance(sdata, dict) else None
            if isinstance(last_url, str) and last_url:
                try:
                    await engine.goto(last_url)
                except Exception as nav_exc:
                    logger.warning(
                        "Resume navigation failed for session %s to %s: %r",
                        session_id,
                        last_url,
                        nav_exc,
                    )
        except Exception as st_exc:
            logger.debug("No prior session URL to resume for %s: %r", session_id, st_exc)
        await engine.health_check()
        try:
            from swarm.distributed.session_lifecycle import lifecycle_manager

            await lifecycle_manager.heartbeat_session(session_id)
        except Exception as hb_exc:
            logger.warning(
                "Lifecycle heartbeat failed for session %s during start: %r",
                session_id,
                hb_exc,
                exc_info=True,
            )

        return {"success": True, "session_id": session_id}
    finally:
        if auto_cleanup:
            await self.auto_cleanup_session(session_id)


@typed_task(base=BrowserTask, bind=True, name="browser.cleanup")
async def cleanup(self: BrowserTask, session_id: str) -> CleanupTaskResponse:
    """Clean up a browser session.

    Single source of truth - all cleanup goes through SessionLifecycleManager.

    Args:
        session_id: The session ID to cleanup

    Returns:
        Dict with cleanup status
    """
    from swarm.distributed.session_lifecycle import lifecycle_manager

    # Single source of truth - lifecycle manager owns all cleanup logic
    await lifecycle_manager.unregister_session(session_id)

    return {"success": True, "session_id": session_id}


# Register cleanup on worker shutdown
@signals.worker_shutdown.connect
def cleanup_engines_on_shutdown(**kwargs: object) -> None:
    """Clean up browser engines when worker shuts down.

    Uses lifecycle manager for coordinated shutdown across all sessions.
    """
    from swarm.distributed.session_lifecycle import lifecycle_manager

    # Lifecycle manager handles full cleanup:
    # - Stops background cleanup loop
    # - Cleans all tracked sessions
    # - Stops all engines gracefully
    # - Clears all affinity mappings
    lifecycle_manager.stop()
    logger.info("Browser engine cleanup completed on worker shutdown")


@typed_task(bind=True, name="browser.scrape_data")
def scrape_data(self: TaskType, url: str, actions: list[Action]) -> ScrapeDataResponse:
    """
    High-level orchestration task to scrape data from a web page with actions.

    Uses Celery group for parallel execution of browser actions.

    Args:
        url: URL to scrape
        actions: List of actions to perform (e.g., click, fill, wait, screenshot)

    Returns:
        Dict with scraped data and results
    """
    # Use Celery request id as default session id for orchestration
    session_id = self.request.id
    results: list[ScrapeDataItem] = []

    try:
        # Navigate first
        nav_result = app.send_task(
            "browser.goto", kwargs={"url": url, "session_id": session_id}
        ).get(timeout=30)
        results.append({"action": {"type": "navigate"}, "result": nav_result})

        # Build a group of tasks for parallel execution
        tasks: list[Signature[object]] = []
        action_indices: list[int] = []  # Track which actions map to tasks

        for i, action in enumerate(actions):
            if is_click_action(action):
                selector = action["selector"]
                tasks.append(
                    app.signature(
                        "browser.click",
                        kwargs={"selector": selector, "session_id": session_id},
                    )
                )
                action_indices.append(i)
            elif is_fill_action(action):
                selector = action["selector"]
                text = action["text"]
                tasks.append(
                    app.signature(
                        "browser.fill",
                        kwargs={
                            "selector": selector,
                            "text": text,
                            "session_id": session_id,
                        },
                    )
                )
                action_indices.append(i)
            elif is_wait_action(action):
                selector = action["selector"]
                state = action.get("state", "visible")
                tasks.append(
                    app.signature(
                        "browser.wait_for",
                        kwargs={
                            "selector": selector,
                            "state": state,
                            "session_id": session_id,
                        },
                    )
                )
                action_indices.append(i)
            elif is_screenshot_action(action):
                tasks.append(app.signature("browser.screenshot", kwargs={"session_id": session_id}))
                action_indices.append(i)
            else:
                results.append(
                    {"action": action_as_plain(action), "result": {"error": "Unknown action type"}}
                )

        # Execute all tasks in parallel if there are any
        if tasks:
            job_group = group(*tasks)
            group_results = job_group.apply_async().get(timeout=60)

            # Map results back to their actions
            for task_idx, action_idx in enumerate(action_indices):
                results.append(
                    {
                        "action": action_as_plain(actions[action_idx]),
                        "result": group_results[task_idx],
                    }
                )

        return {"success": True, "session_id": session_id, "url": url, "results": results}

    finally:
        # Schedule cleanup as a separate task
        app.send_task("browser.cleanup", kwargs={"session_id": session_id})
