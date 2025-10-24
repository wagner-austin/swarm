"""
Celery-based Remote Browser Runtime

Replaces the old RemoteBrowserRuntime with Celery task invocations.
This provides better reliability, monitoring, and scalability.
"""

import asyncio
import base64
import logging
from typing import Any, Dict, Optional

from celery import group
from celery.result import AsyncResult

from swarm.celery_app import app

logger = logging.getLogger(__name__)


class CeleryBrowserRuntime:
    """
    Browser runtime that uses Celery tasks instead of custom broker.

    Each method maps to a Celery task in swarm.tasks.browser.
    Sessions are automatically task-scoped and cleaned up.
    """

    def __init__(self) -> None:
        self._active_sessions: dict[str, AsyncResult[Any]] = {}
        # Optional default session id to use when caller does not supply one
        self._current_session_id: str | None = None

    def set_session(self, session_id: str) -> None:
        """Set the default session id for subsequent operations."""
        self._current_session_id = session_id

    def _resolve_session_id(self, session_id: str | None) -> str | None:
        return session_id or self._current_session_id

    async def goto(
        self, url: str, worker_hint: str | None = None, session_id: str | None = None
    ) -> None:
        """Navigate to a URL using an optionally sticky session."""
        sid = self._resolve_session_id(session_id)
        # If we have no session, proactively create one to enable affinity
        if sid is None:
            await self.start()
            sid = self._current_session_id

        kwargs: dict[str, Any] = {"url": url}
        if sid:
            kwargs["session_id"] = sid

        result = app.send_task("browser.goto", kwargs=kwargs, queue="browser")

        # Wait for result
        response = await asyncio.get_event_loop().run_in_executor(None, result.get, 30.0)

        if not response.get("success"):
            raise RuntimeError(f"Navigation failed: {response.get('error', 'Unknown error')}")

    async def click(
        self, selector: str, worker_hint: str | None = None, session_id: str | None = None
    ) -> None:
        """Click an element (fire-and-forget)."""
        sid = self._resolve_session_id(session_id)
        kwargs: dict[str, Any] = {"selector": selector}
        if sid:
            kwargs["session_id"] = sid
        app.send_task("browser.click", kwargs=kwargs, queue="browser")
        # Fire and forget - don't wait for result

    async def start(self, worker_hint: str | None = None, session_id: str | None = None) -> None:
        """Start a browser session. If session_id provided, reuse it."""
        kwargs: dict[str, Any] = {}
        if session_id:
            kwargs["session_id"] = session_id

        result = app.send_task("browser.start", kwargs=kwargs or None, queue="browser")

        response = await asyncio.get_event_loop().run_in_executor(None, result.get, 30.0)

        if not response.get("success"):
            raise RuntimeError(f"Start failed: {response.get('error', 'Unknown error')}")

        # Store task ID for session tracking
        sid = response.get("session_id") or session_id
        if sid is None:
            raise RuntimeError("Start did not return session_id")
        self._active_sessions[sid] = result
        # Update current session id
        self._current_session_id = sid

    async def screenshot(
        self,
        filename: str | None = None,
        worker_hint: str | None = None,
        session_id: str | None = None,
    ) -> bytes:
        """Take a screenshot."""
        sid = self._resolve_session_id(session_id)
        # Ensure session exists to keep affinity
        if sid is None:
            await self.start()
            sid = self._current_session_id

        kwargs: dict[str, Any] = {}
        if sid:
            kwargs["session_id"] = sid

        result = app.send_task("browser.screenshot", kwargs=kwargs or None, queue="browser")

        response = await asyncio.get_event_loop().run_in_executor(None, result.get, 30.0)

        if not response.get("success"):
            raise RuntimeError(f"Screenshot failed: {response.get('error', 'Unknown error')}")

        # Decode base64 data
        return base64.b64decode(response["data"])

    async def status(
        self, worker_hint: str | None = None, session_id: str | None = None
    ) -> dict[str, Any]:
        """Get browser status."""
        # If a specific session is requested, query just that session first
        sid = self._resolve_session_id(session_id)
        if sid:
            status_result = app.send_task(
                "browser.status", kwargs={"session_id": sid}, queue="browser"
            )
            try:
                response = await asyncio.get_event_loop().run_in_executor(
                    None, status_result.get, 5.0
                )
                if response.get("success"):
                    return {"active_sessions": 1, "sessions": [response["data"]]}
            except Exception as e:
                logger.warning(f"Failed to get status for session {sid}: {e}")

        # Get status for all active tasks
        statuses = []

        for sid2, result in list(self._active_sessions.items()):
            status_result = app.send_task(
                "browser.status", kwargs={"session_id": sid2}, queue="browser"
            )

            try:
                response = await asyncio.get_event_loop().run_in_executor(
                    None, status_result.get, 5.0
                )

                if response.get("success") and response["data"]["status"] == "not_found":
                    # Task no longer exists, remove from tracking
                    del self._active_sessions[sid2]
                else:
                    statuses.append(response["data"])
            except Exception as e:
                logger.warning(f"Failed to get status for session {sid2}: {e}")

        return {"active_sessions": len(statuses), "sessions": statuses}

    async def cleanup_all(self) -> None:
        """Clean up all tracked browser sessions."""
        cleanup_tasks = []

        for sid3 in list(self._active_sessions.keys()):
            cleanup_result = app.send_task("browser.cleanup", kwargs={"session_id": sid3}, queue="browser")
            cleanup_tasks.append(cleanup_result)

        # Wait for all cleanups to complete
        if cleanup_tasks:
            group_result = group(*cleanup_tasks)()
            await asyncio.get_event_loop().run_in_executor(None, group_result.get, 10.0)

        self._active_sessions.clear()

    async def scrape_data(self, url: str, actions: list[dict[str, Any]]) -> dict[str, Any]:
        """
        High-level scraping task.

        Args:
            url: URL to scrape
            actions: List of actions to perform

        Returns:
            Scraped data and results
        """
        result = app.send_task(
            "browser.scrape_data", kwargs={"url": url, "actions": actions}, queue="browser"
        )

        response = await asyncio.get_event_loop().run_in_executor(None, result.get, 60.0)

        if not response.get("success"):
            raise RuntimeError(f"Scraping failed: {response}")

        return dict(response)
