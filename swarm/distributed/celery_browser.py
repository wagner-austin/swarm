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
        self._active_tasks: dict[str, AsyncResult] = {}

    async def goto(self, url: str, worker_hint: str | None = None) -> None:
        """Navigate to a URL."""
        result = app.send_task("browser.goto", kwargs={"url": url}, queue="browser")

        # Wait for result
        response = await asyncio.get_event_loop().run_in_executor(None, result.get, 30.0)

        if not response.get("success"):
            raise RuntimeError(f"Navigation failed: {response.get('error', 'Unknown error')}")

    async def click(self, selector: str, worker_hint: str | None = None) -> None:
        """Click an element (fire-and-forget)."""
        app.send_task("browser.click", kwargs={"selector": selector}, queue="browser")
        # Fire and forget - don't wait for result

    async def start(self, worker_hint: str | None = None) -> None:
        """Start a browser session."""
        result = app.send_task("browser.start", queue="browser")

        response = await asyncio.get_event_loop().run_in_executor(None, result.get, 30.0)

        if not response.get("success"):
            raise RuntimeError(f"Start failed: {response.get('error', 'Unknown error')}")

        # Store task ID for session tracking
        self._active_tasks[response["task_id"]] = result

    async def screenshot(
        self, filename: str | None = None, worker_hint: str | None = None
    ) -> bytes:
        """Take a screenshot."""
        result = app.send_task("browser.screenshot", queue="browser")

        response = await asyncio.get_event_loop().run_in_executor(None, result.get, 30.0)

        if not response.get("success"):
            raise RuntimeError(f"Screenshot failed: {response.get('error', 'Unknown error')}")

        # Decode base64 data
        return base64.b64decode(response["data"])

    async def status(self, worker_hint: str | None = None) -> dict[str, Any]:
        """Get browser status."""
        # Get status for all active tasks
        statuses = []

        for task_id, result in list(self._active_tasks.items()):
            status_result = app.send_task(
                "browser.status", kwargs={"task_id": task_id}, queue="browser"
            )

            try:
                response = await asyncio.get_event_loop().run_in_executor(
                    None, status_result.get, 5.0
                )

                if response.get("success") and response["data"]["status"] == "not_found":
                    # Task no longer exists, remove from tracking
                    del self._active_tasks[task_id]
                else:
                    statuses.append(response["data"])
            except Exception as e:
                logger.warning(f"Failed to get status for task {task_id}: {e}")

        return {"active_sessions": len(statuses), "sessions": statuses}

    async def cleanup_all(self) -> None:
        """Clean up all tracked browser sessions."""
        cleanup_tasks = []

        for task_id in list(self._active_tasks.keys()):
            cleanup_result = app.send_task("browser.cleanup", args=[task_id], queue="browser")
            cleanup_tasks.append(cleanup_result)

        # Wait for all cleanups to complete
        if cleanup_tasks:
            group_result = group(*cleanup_tasks)()
            await asyncio.get_event_loop().run_in_executor(None, group_result.get, 10.0)

        self._active_tasks.clear()

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
