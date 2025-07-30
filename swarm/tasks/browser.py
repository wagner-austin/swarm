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
from celery import Celery, Task, group

from swarm.browser.engine import BrowserEngine
from swarm.celery_app import app
from swarm.core.settings import Settings
from swarm.tasks._base import SwarmTask
from swarm.types import RedisBytes

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


# Module-level storage for browser engines (per worker process)
_engines: dict[str, BrowserEngine] = {}

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

    async def get_or_create_engine(self, task_id: str) -> BrowserEngine:
        """Get existing browser engine or create a new one for the task."""
        engine = _engines.get(task_id)

        # Check if engine exists but has a closed event loop
        if engine:
            try:
                # Check if the engine's event loop is closed
                if hasattr(engine, "_loop") and engine._loop and engine._loop.is_closed():
                    logger.warning(f"Engine for task {task_id} has closed event loop, recreating")
                    await engine.stop(graceful=True)
                    del _engines[task_id]
                    engine = None
            except Exception as e:
                logger.error(f"Error checking engine state: {e}")
                del _engines[task_id]
                engine = None

        if engine:
            return engine

        logger.info(f"Creating browser engine for task {task_id}")
        engine = BrowserEngine(headless=True, proxy=None, timeout_ms=60000)
        await engine.start()

        _engines[task_id] = engine
        redis = await self.get_redis()

        # Store session metadata in Redis hash
        session_data = {
            "worker": str(self.request.hostname or "unknown"),
            "status": "active",
            "created_at": str(asyncio.get_event_loop().time()),
            "url": "none",  # Will be updated by goto
        }
        await redis.hset(
            f"browser:session:{task_id}", mapping={k: v for k, v in session_data.items()}
        )
        await redis.expire(f"browser:session:{task_id}", 3600)

        return engine

    async def cleanup_engine(self, task_id: str) -> None:
        """Clean up browser engine for a task."""
        engine = _engines.pop(task_id, None)
        if engine:
            try:
                await engine.stop(graceful=True)
                logger.info(f"Cleaned up browser engine for task {task_id}")
            except Exception as e:
                logger.error(f"Error cleaning up browser engine: {e}")

        try:
            redis = await self.get_redis()
            await redis.delete(f"browser:session:{task_id}")
        except Exception as e:
            logger.error(f"Error cleaning up Redis session data: {e}")

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
async def goto(self: BrowserTask, url: str, task_id: str | None = None) -> dict[str, Any]:
    """
    Navigate to a URL within a task's browser session.

    Args:
        url: The URL to navigate to
        task_id: Task ID for session management (defaults to current task)

    Returns:
        Dict with success status and navigation details
    """
    task_id = self.resolve_task_id(task_id)

    engine = await self.get_or_create_engine(task_id)
    await engine.goto(url)

    # Update session metadata with current URL
    redis = await self.get_redis()
    await redis.hset(f"browser:session:{task_id}", "url", url)

    return {"success": True, "task_id": task_id, "url": url}


@typed_task(base=BrowserTask, bind=True, name="browser.click")
async def click(self: BrowserTask, selector: str, task_id: str | None = None) -> dict[str, Any]:
    """
    Click an element within a task's browser session.

    Args:
        selector: CSS selector for the element
        task_id: Task ID for session management (defaults to current task)

    Returns:
        Dict with click result
    """
    task_id = self.resolve_task_id(task_id)

    engine = await self.get_or_create_engine(task_id)
    await engine.click(selector)

    return {"success": True, "task_id": task_id, "selector": selector}


@typed_task(base=BrowserTask, bind=True, name="browser.fill")
async def fill(
    self: BrowserTask, selector: str, text: str, task_id: str | None = None
) -> dict[str, Any]:
    """
    Fill a form field within a task's browser session.

    Args:
        selector: CSS selector for the field
        text: Text to fill
        task_id: Task ID for session management (defaults to current task)

    Returns:
        Dict with fill result
    """
    task_id = self.resolve_task_id(task_id)

    engine = await self.get_or_create_engine(task_id)
    await engine.fill(selector, text)

    return {"success": True, "task_id": task_id, "selector": selector, "text": text}


@typed_task(base=BrowserTask, bind=True, name="browser.upload")
async def upload(
    self: BrowserTask, selector: str, file_path: str, task_id: str | None = None
) -> dict[str, Any]:
    """
    Upload a file to a form field.

    Args:
        selector: CSS selector for the file input
        file_path: Path to the file to upload
        task_id: Task ID for session management (defaults to current task)

    Returns:
        Dict with upload result
    """
    task_id = self.resolve_task_id(task_id)

    engine = await self.get_or_create_engine(task_id)
    await engine.upload(selector, Path(file_path))

    return {"success": True, "task_id": task_id, "selector": selector, "file_path": file_path}


@typed_task(base=BrowserTask, bind=True, name="browser.wait_for")
async def wait_for(
    self: BrowserTask,
    selector: str,
    state: Literal["visible", "hidden", "attached", "detached"] = "visible",
    task_id: str | None = None,
) -> dict[str, Any]:
    """
    Wait for an element to reach a specific state.

    Args:
        selector: CSS selector to wait for
        state: State to wait for
        task_id: Task ID for session management (defaults to current task)

    Returns:
        Dict with wait result
    """
    task_id = self.resolve_task_id(task_id)

    engine = await self.get_or_create_engine(task_id)
    await engine.wait_for(selector, state)

    return {"success": True, "task_id": task_id, "selector": selector, "state": state}


@typed_task(base=BrowserTask, bind=True, name="browser.screenshot")
async def screenshot(self: BrowserTask, task_id: str | None = None) -> dict[str, Any]:
    """
    Take a screenshot within a task's browser session.

    Args:
        task_id: Task ID for session management (defaults to current task)

    Returns:
        Dict with base64 encoded screenshot
    """
    task_id = self.resolve_task_id(task_id)

    engine = await self.get_or_create_engine(task_id)

    temp_path = os.path.join(tempfile.gettempdir(), f"screenshot_{task_id}_{os.getpid()}.png")

    try:
        await engine.screenshot(temp_path)

        with open(temp_path, "rb") as f:
            image_data = f.read()

        return {
            "success": True,
            "task_id": task_id,
            "data": base64.b64encode(image_data).decode("utf-8"),
        }
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


@typed_task(base=BrowserTask, bind=True, name="browser.status")
async def status(self: BrowserTask, task_id: str | None = None) -> dict[str, Any]:
    """
    Get status of a browser session.

    Args:
        task_id: Task ID for session management (defaults to current task)

    Returns:
        Dict with session status
    """
    task_id = self.resolve_task_id(task_id)

    if task_id in _engines:
        engine = _engines[task_id]
        engine_status = await engine.status()
        return {"success": True, "data": engine_status}
    else:
        redis = await self.get_redis()
        session_data = await redis.hgetall(f"browser:session:{task_id}")

        if session_data:
            # Decode bytes to strings
            decoded_data = {k.decode(): v.decode() for k, v in session_data.items()}
            return {
                "success": True,
                "data": {"task_id": task_id, **decoded_data},
            }
        else:
            return {
                "success": True,
                "data": {
                    "task_id": task_id,
                    "status": "not_found",
                },
            }


@typed_task(base=BrowserTask, bind=True, name="browser.start")
async def start(self: BrowserTask, task_id: str | None = None) -> dict[str, Any]:
    """
    Explicitly start a browser session for a task.

    Args:
        task_id: Task ID for session management (defaults to current task)

    Returns:
        Dict with session start result
    """
    task_id = self.resolve_task_id(task_id)

    engine = await self.get_or_create_engine(task_id)
    await engine.health_check()

    return {"success": True, "task_id": task_id}


@typed_task(base=BrowserTask, bind=True, name="browser.cleanup")
async def cleanup(self: BrowserTask, task_id: str) -> dict[str, Any]:
    """
    Clean up a browser session for a task.

    Args:
        task_id: The task ID to cleanup

    Returns:
        Dict with cleanup status
    """
    await self.cleanup_engine(task_id)

    return {"success": True, "task_id": task_id}


@app.task(bind=True, name="browser.scrape_data")
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
    task_id = self.request.id
    results = []

    try:
        # Navigate first
        nav_result = app.send_task("browser.goto", kwargs={"url": url, "task_id": task_id}).get(
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
                        "browser.click", kwargs={"selector": action["selector"], "task_id": task_id}
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
                            "task_id": task_id,
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
                            "task_id": task_id,
                        },
                    )
                )
                action_indices.append(i)
            elif action_type == "screenshot":
                tasks.append(app.signature("browser.screenshot", kwargs={"task_id": task_id}))
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

        return {"success": True, "task_id": task_id, "url": url, "results": results}

    finally:
        # Schedule cleanup as a separate task
        app.send_task("browser.cleanup", kwargs={"task_id": task_id})
