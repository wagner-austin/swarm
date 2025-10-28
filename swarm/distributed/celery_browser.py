"""
Celery-based Remote Browser Runtime

Replaces the old RemoteBrowserRuntime with Celery task invocations.
This provides better reliability, monitoring, and scalability.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from typing import Callable, TypeVar

from swarm.browser.types import (
    BrowserEngineStatus,
    BrowserStatusAggregate,
    GotoTaskResponse,
    ScrapeDataResponse,
    ScreenshotTaskResponse,
    StartTaskResponse,
    StatusTaskResponse,
)
from swarm.celery_app import app

R = TypeVar("R")
logger = logging.getLogger(__name__)


class CeleryBrowserRuntime:
    """
    Browser runtime that uses Celery tasks instead of custom broker.

    Each method maps to a Celery task in swarm.tasks.browser.
    Sessions are automatically task-scoped and cleaned up.
    """

    def __init__(self) -> None:
        self._active_sessions: set[str] = set()
        # Optional default session id to use when caller does not supply one
        self._current_session_id: str | None = None

    def set_session(self, session_id: str) -> None:
        """Set the default session id for subsequent operations."""
        self._current_session_id = session_id

    def _resolve_session_id(self, session_id: str | None) -> str | None:
        return session_id or self._current_session_id

    @staticmethod
    def _wait_result_polling(getter: Callable[[float], R], deadline_s: float) -> R:
        """Wait for a Celery result with short-window polling to avoid idle closes.

        Uses repeated small timeouts up to a firm deadline. Raises on final timeout.
        """
        from celery.exceptions import TimeoutError as CeleryTimeoutError  # local import

        end = time.time() + deadline_s
        while True:
            remaining = end - time.time()
            if remaining <= 0:
                raise CeleryTimeoutError("Operation timed out")
            per_attempt = 2.0 if remaining > 2.0 else max(0.1, remaining)
            try:
                return getter(per_attempt)
            except CeleryTimeoutError:
                continue

    async def goto(
        self, url: str, worker_hint: str | None = None, session_id: str | None = None
    ) -> None:
        """Navigate to a URL using an optionally sticky session."""
        sid = self._resolve_session_id(session_id)
        # If we have no session, proactively create one to enable affinity
        if sid is None:
            await self.start()
            sid = self._current_session_id

        kwargs: dict[str, object] = {"url": url}
        if sid:
            kwargs["session_id"] = sid

        res = app.send_task("browser.goto", kwargs=kwargs, queue="browser")

        # Wait for result
        response: GotoTaskResponse = await asyncio.to_thread(
            CeleryBrowserRuntime._wait_result_polling, res.get, 30.0
        )
        if not response["success"]:
            raise RuntimeError("Navigation failed")

    async def click(
        self, selector: str, worker_hint: str | None = None, session_id: str | None = None
    ) -> None:
        """Click an element (fire-and-forget)."""
        sid = self._resolve_session_id(session_id)
        kwargs: dict[str, object] = {"selector": selector}
        if sid:
            kwargs["session_id"] = sid
        app.send_task("browser.click", kwargs=kwargs, queue="browser")
        # Fire and forget - don't wait for result

    async def start(self, worker_hint: str | None = None, session_id: str | None = None) -> None:
        """Start a browser session. If session_id provided, reuse it."""
        kwargs: dict[str, object] = {}
        if session_id:
            kwargs["session_id"] = session_id

        res = app.send_task("browser.start", kwargs=kwargs or None, queue="browser")

        response: StartTaskResponse = await asyncio.to_thread(
            CeleryBrowserRuntime._wait_result_polling, res.get, 30.0
        )
        if not response["success"]:
            raise RuntimeError("Start failed")

        # Store task ID for session tracking
        sid = response.get("session_id") or session_id
        if sid is None:
            raise RuntimeError("Start did not return session_id")
        self._active_sessions.add(sid)
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

        kwargs: dict[str, object] = {}
        if sid:
            kwargs["session_id"] = sid

        res = app.send_task("browser.screenshot", kwargs=kwargs or None, queue="browser")

        response: ScreenshotTaskResponse = await asyncio.to_thread(
            CeleryBrowserRuntime._wait_result_polling, res.get, 30.0
        )
        if not response["success"]:
            raise RuntimeError("Screenshot failed")

        # Decode base64 data
        return base64.b64decode(response["data"])

    async def status(
        self, worker_hint: str | None = None, session_id: str | None = None
    ) -> BrowserStatusAggregate:
        """Get browser status."""
        # If a specific session is requested, query just that session first
        sid = self._resolve_session_id(session_id)
        if sid:
            res_single = app.send_task(
                "browser.status", kwargs={"session_id": sid}, queue="browser"
            )
            try:
                response = await asyncio.to_thread(
                    CeleryBrowserRuntime._wait_result_polling, res_single.get, 5.0
                )
                if response.get("success"):
                    single: BrowserStatusAggregate = {
                        "active_sessions": 1,
                        "sessions": [response["data"]],
                    }
                    return single
            except Exception as e:
                logger.warning(f"Failed to get status for session {sid}: {e}")

        # Get status for all active tasks
        statuses: list[BrowserEngineStatus] = []

        for sid2 in list(self._active_sessions):
            res_loop = app.send_task("browser.status", kwargs={"session_id": sid2}, queue="browser")

            try:
                response = await asyncio.to_thread(
                    CeleryBrowserRuntime._wait_result_polling, res_loop.get, 5.0
                )

                if response.get("success") and response["data"]["status"] == "not_found":
                    # Task no longer exists, remove from tracking
                    self._active_sessions.discard(sid2)
                else:
                    statuses.append(response["data"])
            except Exception as e:
                logger.warning(f"Failed to get status for session {sid2}: {e}")

        aggregate: BrowserStatusAggregate = {
            "active_sessions": len(statuses),
            "sessions": statuses,
        }
        return aggregate

    async def cleanup_all(self) -> None:
        """Clean up all tracked browser sessions."""
        cleanup_tasks = []

        for sid3 in list(self._active_sessions):
            cleanup_result = app.send_task(
                "browser.cleanup", kwargs={"session_id": sid3}, queue="browser"
            )
            cleanup_tasks.append(cleanup_result.get)

        # Wait for all cleanups to complete: fetch each result with a timeout
        if cleanup_tasks:
            for getter in cleanup_tasks:
                try:
                    await asyncio.to_thread(CeleryBrowserRuntime._wait_result_polling, getter, 10.0)
                except Exception as e:
                    logger.warning(f"Cleanup task failed: {e}")

        self._active_sessions.clear()

    async def scrape_data(self, url: str, actions: list[dict[str, object]]) -> ScrapeDataResponse:
        """
        High-level scraping task.

        Args:
            url: URL to scrape
            actions: List of actions to perform

        Returns:
            Scraped data and results
        """
        res = app.send_task(
            "browser.scrape_data", kwargs={"url": url, "actions": actions}, queue="browser"
        )

        response: ScrapeDataResponse = await asyncio.to_thread(
            CeleryBrowserRuntime._wait_result_polling, res.get, 60.0
        )
        if not response["success"]:
            raise RuntimeError("Scraping failed")
        return response
