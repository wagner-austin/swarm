"""
Browser automation tasks for Celery.

Production-grade task-scoped browser automation for the AI Task Assistant.
Each task gets its own browser session that auto-cleans up on completion.
"""

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
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Concatenate,
    Dict,
    Literal,
    Optional,
    ParamSpec,
    TypeVar,
    cast,
)

import redis.asyncio as redis_asyncio
from celery import Celery, Task, group, signals

from swarm.browser.engine import BrowserEngine
from swarm.celery_app import app
from swarm.core.settings import Settings
from swarm.tasks._base import SwarmTask
from swarm.types import RedisBytes
from swarm.distributed.worker_lifecycle import WorkerLifecycle

# Type for the creating sentinel
_CreatingSentinel = Literal["__creating__"]

if TYPE_CHECKING:
    # For type checking, use the generic version
    TaskType = Task[Any, Any]
else:
    # At runtime, use the non-generic version
    TaskType = Task

_P = ParamSpec("_P")
_R = TypeVar("_R")

logger = logging.getLogger(__name__)


def typed_task(*task_args: Any, **task_kwargs: Any) -> Callable[[Callable[..., Any]], Any]:
    """
    Register a function as a Celery task and transparently bridge async
    coroutines to the (threads) worker pool using thread-safe execution.
    """

    def decorator(fn: Callable[..., Any]) -> Any:
        if asyncio.iscoroutinefunction(fn):

            @wraps(fn)
            def sync_wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
                # Get stable thread-local event loop
                if isinstance(self, SwarmTask):
                    loop = self.get_loop()
                    # Run the coroutine to completion on this thread's loop
                    return loop.run_until_complete(fn(self, *args, **kwargs))
                else:
                    # Fallback for non-SwarmTask instances
                    return asyncio.run(fn(self, *args, **kwargs))

            # Ensure base=SwarmTask for all tasks
            task_kwargs.setdefault("base", SwarmTask)
            return app.task(*task_args, **task_kwargs)(sync_wrapper)

        # Plain sync function
        task_kwargs.setdefault("base", SwarmTask)
        return app.task(*task_args, **task_kwargs)(fn)

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
_loop_clients: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, RedisBytes] = (
    weakref.WeakKeyDictionary()
)


class BrowserTask(SwarmTask):
    """Base task for browser operations with session management."""

    async def get_redis(self) -> RedisBytes:
        """Get or create Redis client for the current event loop."""
        loop = asyncio.get_running_loop()
        client = _loop_clients.get(loop)

        if client is None:
            settings = Settings()
            if not settings.redis.url:
                raise ValueError("Redis URL not configured")

            # Create client with limited connection pool for thread pool workers
            # Each thread gets its own loop and client, so we don't need many connections
            client = redis_asyncio.from_url(
                settings.redis.url,
                max_connections=2,  # Limit connections per event loop
            )
            _loop_clients[loop] = client
            logger.debug(f"Created new Redis client for event loop {id(loop)}")

        return client

    async def get_or_create_engine(self, session_id: str) -> BrowserEngine:
        """Return the BrowserEngine for session_id, creating it once in a thread-safe way."""
        # Fast path: someone already created it
        with _engines_lock:
            existing = _engines.get(session_id)
            if isinstance(existing, BrowserEngine):
                thread_id = threading.current_thread().ident
                logger.info(f"Session {session_id} on thread {thread_id} found existing engine")
                return existing
            if existing is _CREATING_SENTINEL:
                # Another thread is creating; fall through to wait loop
                logger.info(f"Another thread is creating engine for {session_id}, waiting...")
                pass
            else:
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
                    logger.info(f"Stored engine for session {session_id} (total engines: {engine_count})")

                # Register session with affinity registry
                from swarm.distributed.session_registry import SessionRegistry

                try:
                    registry = SessionRegistry()
                    worker_id = str(self.request.hostname or "unknown")
                    # Sanitize worker ID to match router's expectations
                    worker_id = worker_id.replace("@", "_")
                    logger.info(f"Registering affinity for session {session_id} to worker {worker_id}")
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

                return engine
            except Exception as e:
                # Creation failed - remove sentinel
                with _engines_lock:
                    if _engines.get(session_id) is _CREATING_SENTINEL:
                        del _engines[session_id]
                logger.error(f"Failed to create engine for {session_id}: {e}")
                raise

    async def cleanup_engine(self, session_id: str) -> None:
        """Clean up browser engine for a task."""
        # Pop inside the lock
        with _engines_lock:
            engine = _engines.pop(session_id, None)

        # Stop the engine outside the lock to avoid blocking other threads
        if isinstance(engine, BrowserEngine):
            try:
                await engine.stop(graceful=True)
                logger.info(f"Cleaned up browser engine for session {session_id}")
            except Exception as e:
                logger.error(f"Error cleaning up browser engine: {e}")

        try:
            # Cleanup the session metadata hash (used by goto/status)
            redis = await self.get_redis()
            await redis.delete(f"browser:session:{session_id}")
        except Exception as e:
            logger.debug(f"Session metadata cleanup skipped: {e}")

        # Always clear the affinity registry and update lifecycle ownership
        try:
            from swarm.distributed.session_registry import SessionRegistry

            registry = SessionRegistry()
            # Remove session from lifecycle set for this worker
            try:
                worker_id = str(self.request.hostname or "unknown").replace("@", "_")
                WorkerLifecycle(worker_id).remove_session(session_id)
            except Exception as le:
                logger.warning(f"Failed to remove session from lifecycle: {le}")
            await registry.clear_owner(session_id)
        except Exception as e:
            logger.error(f"Error clearing session from registry: {e}")

    def on_failure(
        self,
        exc: Exception,
        task_id: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        einfo: Any,
    ) -> None:
        """Clean up on task failure."""
        # Don't schedule cleanup here - rely on the finally block in each task
        # to avoid double cleanup. The finally block will run even on failure.
        super().on_failure(exc, task_id, args, kwargs, einfo)


@typed_task(base=BrowserTask, bind=True, name="browser.goto")
async def goto(self: BrowserTask, url: str, session_id: str | None = None) -> dict[str, Any]:
    """
    Navigate to a URL within a task's browser session.

    Args:
        url: The URL to navigate to
        session_id: Session ID for session management (defaults to current task)

    Returns:
        Dict with success status and navigation details
    """
    session_id = self.resolve_session_id(session_id)

    engine = await self.get_or_create_engine(session_id)
    await engine.goto(url)

    # Update session metadata with current URL
    redis = await self.get_redis()
    await redis.hset(f"browser:session:{session_id}", "url", url)

    return {"success": True, "session_id": session_id, "url": url}


@typed_task(base=BrowserTask, bind=True, name="browser.click")
async def click(
    self: BrowserTask, selector: str, session_id: str | None = None, no_wait_after: bool = False
) -> dict[str, Any]:
    """
    Click an element within a task's browser session.

    Args:
        selector: CSS selector for the element
        session_id: Session ID for session management (defaults to current task)

    Returns:
        Dict with click result
    """
    session_id = self.resolve_session_id(session_id)

    engine = await self.get_or_create_engine(session_id)
    await engine.click(selector, no_wait_after=no_wait_after)

    return {"success": True, "session_id": session_id, "selector": selector}


@typed_task(base=BrowserTask, bind=True, name="browser.fill")
async def fill(
    self: BrowserTask, selector: str, text: str, session_id: str | None = None
) -> dict[str, Any]:
    """
    Fill a form field within a task's browser session.

    Args:
        selector: CSS selector for the field
        text: Text to fill
        session_id: Session ID for session management (defaults to current task)

    Returns:
        Dict with fill result
    """
    session_id = self.resolve_session_id(session_id)

    engine = await self.get_or_create_engine(session_id)
    await engine.fill(selector, text)

    return {"success": True, "session_id": session_id, "selector": selector, "text": text}


@typed_task(base=BrowserTask, bind=True, name="browser.upload")
async def upload(
    self: BrowserTask, selector: str, file_path: str, session_id: str | None = None
) -> dict[str, Any]:
    """
    Upload a file to a form field.

    Args:
        selector: CSS selector for the file input
        file_path: Path to the file to upload
        session_id: Session ID for session management (defaults to current task)

    Returns:
        Dict with upload result
    """
    session_id = self.resolve_session_id(session_id)

    engine = await self.get_or_create_engine(session_id)
    await engine.upload(selector, Path(file_path))

    return {"success": True, "session_id": session_id, "selector": selector, "file_path": file_path}


@typed_task(base=BrowserTask, bind=True, name="browser.wait_for")
async def wait_for(
    self: BrowserTask,
    selector: str,
    state: Literal["visible", "hidden", "attached", "detached"] = "visible",
    session_id: str | None = None,
) -> dict[str, Any]:
    """
    Wait for an element to reach a specific state.

    Args:
        selector: CSS selector to wait for
        state: State to wait for
        session_id: Session ID for session management (defaults to current task)

    Returns:
        Dict with wait result
    """
    session_id = self.resolve_session_id(session_id)

    engine = await self.get_or_create_engine(session_id)
    await engine.wait_for(selector, state)

    return {"success": True, "session_id": session_id, "selector": selector, "state": state}


@typed_task(base=BrowserTask, bind=True, name="browser.screenshot")
async def screenshot(self: BrowserTask, session_id: str | None = None) -> dict[str, Any]:
    """
    Take a screenshot within a task's browser session.

    Args:
        session_id: Session ID for session management (defaults to current task)

    Returns:
        Dict with base64 encoded screenshot
    """
    session_id = self.resolve_session_id(session_id)

    engine = await self.get_or_create_engine(session_id)

    temp_path = os.path.join(tempfile.gettempdir(), f"screenshot_{session_id}_{os.getpid()}.png")

    try:
        await engine.screenshot(temp_path)

        with open(temp_path, "rb") as f:
            image_data = f.read()

        return {
            "success": True,
            "session_id": session_id,
            "data": base64.b64encode(image_data).decode("utf-8"),
        }
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


@typed_task(base=BrowserTask, bind=True, name="browser.status")
async def status(self: BrowserTask, session_id: str | None = None) -> dict[str, Any]:
    """
    Get status of a browser session.

    Args:
        session_id: Session ID for session management (defaults to current task)

    Returns:
        Dict with session status
    """
    session_id = self.resolve_session_id(session_id)

    # Check if engine exists in global registry
    with _engines_lock:
        engine = _engines.get(session_id)

    if isinstance(engine, BrowserEngine):
        engine_status = await engine.status()
        return {"success": True, "data": engine_status}
    else:
        redis = await self.get_redis()
        session_data = await redis.hgetall(f"browser:session:{session_id}")

        if session_data:
            # Decode bytes to strings
            decoded_data = {k.decode(): v.decode() for k, v in session_data.items()}
            return {
                "success": True,
                "data": {"session_id": session_id, **decoded_data},
            }
        else:
            return {
                "success": True,
                "data": {
                    "session_id": session_id,
                    "status": "not_found",
                },
            }


@typed_task(base=BrowserTask, bind=True, name="browser.start")
async def start(self: BrowserTask, session_id: str | None = None) -> dict[str, Any]:
    """
    Explicitly start a browser session for a task.

    Args:
        session_id: Session ID for session management (defaults to current task)

    Returns:
        Dict with session start result
    """
    session_id = self.resolve_session_id(session_id)

    engine = await self.get_or_create_engine(session_id)
    await engine.health_check()

    return {"success": True, "session_id": session_id}


@typed_task(base=BrowserTask, bind=True, name="browser.cleanup")
async def cleanup(self: BrowserTask, session_id: str) -> dict[str, Any]:
    """
    Clean up a browser session for a task.

    Args:
        session_id: The session ID to cleanup

    Returns:
        Dict with cleanup status
    """
    await self.cleanup_engine(session_id)

    return {"success": True, "session_id": session_id}


def _cleanup_all_engines() -> None:
    """Clean up all browser engines across all threads.

    Handles engines on different event loops appropriately.
    """
    # Get a copy of all engines and clear the dict under the lock
    with _engines_lock:
        engines_to_clean = [(k, v) for k, v in _engines.items() if isinstance(v, BrowserEngine)]
        _engines.clear()

    if not engines_to_clean:
        return

    logger.info(f"Cleaning up {len(engines_to_clean)} browser engines")
    for session_id, engine in engines_to_clean:
        try:
            if hasattr(engine, "_loop") and engine._loop and not engine._loop.is_closed():
                # For engines with running loops, use thread-safe scheduling
                if engine._loop.is_running():
                    # Properly wrap the coroutine for run_coroutine_threadsafe
                    async def _stop() -> None:
                        await engine.stop(graceful=True)

                    future = asyncio.run_coroutine_threadsafe(_stop(), engine._loop)
                    future.result(timeout=10)  # Wait up to 10s for cleanup
                else:
                    # Loop exists but not running, run directly
                    engine._loop.run_until_complete(engine.stop(graceful=True))
            logger.debug(f"Cleaned up engine for session {session_id}")
        except Exception as exc:
            logger.warning(f"Error shutting down engine for session {session_id}: {exc}")


# Register cleanup on worker shutdown
@signals.worker_shutdown.connect
def cleanup_engines_on_shutdown(**kwargs: Any) -> None:
    """Clean up browser engines when worker shuts down.

    Cleans up all engines regardless of which thread created them.
    """
    _cleanup_all_engines()
    logger.info("Browser engine cleanup completed on worker shutdown")


@typed_task(bind=True, name="browser.scrape_data")
def scrape_data(self: TaskType, url: str, actions: list[dict[str, Any]]) -> dict[str, Any]:
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
    results = []

    try:
        # Navigate first
        nav_result = app.send_task("browser.goto", kwargs={"url": url, "session_id": session_id}).get(
            timeout=30
        )
        results.append({"action": "navigate", "result": nav_result})

        # Build a group of tasks for parallel execution
        tasks = []
        action_indices = []  # Track which actions map to tasks

        for i, action in enumerate(actions):
            action_type = action.get("type")

            if action_type == "click":
                tasks.append(
                    app.signature(
                        "browser.click",
                        kwargs={"selector": action["selector"], "session_id": session_id},
                    )
                )
                action_indices.append(i)
            elif action_type == "fill":
                tasks.append(
                    app.signature(
                        "browser.fill",
                        kwargs={
                            "selector": action["selector"],
                            "text": action["text"],
                            "session_id": session_id,
                        },
                    )
                )
                action_indices.append(i)
            elif action_type == "wait":
                tasks.append(
                    app.signature(
                        "browser.wait_for",
                        kwargs={
                            "selector": action["selector"],
                            "state": action.get("state", "visible"),
                            "session_id": session_id,
                        },
                    )
                )
                action_indices.append(i)
            elif action_type == "screenshot":
                tasks.append(app.signature("browser.screenshot", kwargs={"session_id": session_id}))
                action_indices.append(i)
            else:
                # For unknown actions, add result immediately
                results.append(
                    {"action": action, "result": {"error": f"Unknown action type: {action_type}"}}
                )

        # Execute all tasks in parallel if there are any
        if tasks:
            job_group = group(*tasks)
            group_results = job_group.apply_async().get(timeout=60)

            # Map results back to their actions
            for task_idx, action_idx in enumerate(action_indices):
                results.append({"action": actions[action_idx], "result": group_results[task_idx]})

        return {"success": True, "session_id": session_id, "url": url, "results": results}

    finally:
        # Schedule cleanup as a separate task
        app.send_task("browser.cleanup", kwargs={"session_id": session_id})
