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
from typing import Callable, Literal, TypeVar

import redis.asyncio as redis_asyncio

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
from swarm.core.settings import Settings
from swarm.infra.redis_keys import affinity_key
from swarm.utils.worker_identity import direct_queue_name

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

    async def _resolve_direct_queue(self, session_id: str) -> str | None:
        """Resolve direct worker queue for a session via affinity mapping.

        Returns the direct queue name if available, otherwise None.
        """
        try:
            settings = Settings()
            if not settings.redis.url:
                return None
            r = redis_asyncio.from_url(settings.redis.url, decode_responses=True)
            try:
                m = await r.hgetall(affinity_key(session_id))
            finally:
                try:
                    await r.close()
                except Exception:
                    pass
            if not isinstance(m, dict) or not m:
                return None
            # Normalize keys/values to str to satisfy strict typing
            kv: dict[str, str] = {}
            for k, v in m.items():
                if isinstance(k, str):
                    ks = k
                elif isinstance(k, bytes | bytearray):
                    try:
                        ks = k.decode()
                    except Exception:
                        ks = ""
                else:
                    ks = str(k)
                if isinstance(v, str):
                    vs = v
                elif isinstance(v, bytes | bytearray):
                    try:
                        vs = v.decode()
                    except Exception:
                        vs = ""
                else:
                    vs = str(v)
                kv[ks] = vs
            wid = kv.get("worker_id")
            if isinstance(wid, str) and wid:
                return direct_queue_name(wid)
            dq = kv.get("direct_queue")
            if isinstance(dq, str) and dq:
                return dq
            return None
        except Exception:
            return None

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

        def _to_engine_status(obj: object) -> BrowserEngineStatus:
            d = obj if isinstance(obj, dict) else {}
            # worker_id
            wid = d.get("worker_id") if isinstance(d, dict) else None
            worker_id: str = wid if isinstance(wid, str) else "unknown"

            # status literal
            raw_status = d.get("status") if isinstance(d, dict) else None
            st = raw_status if isinstance(raw_status, str) else "unknown"
            status_literal: Literal["healthy", "unhealthy", "error", "not_found", "unknown"]
            if st == "healthy":
                status_literal = "healthy"
            elif st == "unhealthy":
                status_literal = "unhealthy"
            elif st == "error":
                status_literal = "error"
            elif st == "not_found":
                status_literal = "not_found"
            else:
                status_literal = "unknown"

            # booleans
            browser_active: bool = bool(d.get("browser_active")) if isinstance(d, dict) else False
            page_active: bool = bool(d.get("page_active")) if isinstance(d, dict) else False

            # url
            uo = d.get("url") if isinstance(d, dict) else None
            url: str | None = uo if isinstance(uo, str) else None

            # uptime
            uvt = d.get("uptime") if isinstance(d, dict) else None
            if isinstance(uvt, int | float):
                uptime = float(uvt)
            elif isinstance(uvt, str):
                try:
                    uptime = float(uvt)
                except Exception:
                    uptime = 0.0
            else:
                uptime = 0.0

            # sessions count
            sv = d.get("sessions") if isinstance(d, dict) else None
            if isinstance(sv, int):
                sessions = sv
            elif isinstance(sv, float | str):
                try:
                    sessions = int(float(sv))
                except Exception:
                    sessions = 0
            else:
                sessions = 0

            eng: BrowserEngineStatus = {
                "worker_id": worker_id,
                "status": status_literal,
                "browser_active": browser_active,
                "page_active": page_active,
                "url": url,
                "uptime": uptime,
                "sessions": sessions,
            }

            err = d.get("error") if isinstance(d, dict) else None
            if isinstance(err, str):
                eng["error"] = err
            sidv = d.get("session_id") if isinstance(d, dict) else None
            if isinstance(sidv, str):
                eng["session_id"] = sidv
            return eng

        # If a specific session is requested, query just that session first
        sid = self._resolve_session_id(session_id)
        if sid:
            # Prefer routing to the owning worker's direct queue when known
            queue_name = "browser"
            if isinstance(sid, str):
                q = await self._resolve_direct_queue(sid)
                if isinstance(q, str) and q:
                    queue_name = q
            res_single = app.send_task(
                "browser.status", kwargs={"session_id": sid}, queue=queue_name
            )
            try:
                response: StatusTaskResponse = await asyncio.to_thread(
                    CeleryBrowserRuntime._wait_result_polling, res_single.get, 5.0
                )
                if response.get("success"):
                    data_obj = response.get("data")
                    if isinstance(data_obj, dict) and data_obj.get("status") == "not_found":
                        return {"active_sessions": 0, "sessions": []}
                    eng = _to_engine_status(data_obj)
                    return {"active_sessions": 1, "sessions": [eng]}
            except Exception as e:
                logger.warning(f"Failed to get status for session {sid}: {e}")

        # Get status for all active tasks
        statuses: list[BrowserEngineStatus] = []

        for sid2 in list(self._active_sessions):
            queue_name2 = "browser"
            if isinstance(sid2, str):
                q2 = await self._resolve_direct_queue(sid2)
                if isinstance(q2, str) and q2:
                    queue_name2 = q2
            res_loop = app.send_task(
                "browser.status", kwargs={"session_id": sid2}, queue=queue_name2
            )

            try:
                resp_loop: StatusTaskResponse = await asyncio.to_thread(
                    CeleryBrowserRuntime._wait_result_polling, res_loop.get, 5.0
                )

                if (
                    resp_loop.get("success")
                    and isinstance(resp_loop.get("data"), dict)
                    and resp_loop["data"].get("status") == "not_found"
                ):
                    # Task no longer exists, remove from tracking
                    self._active_sessions.discard(sid2)
                else:
                    eng2 = (
                        _to_engine_status(resp_loop.get("data"))
                        if resp_loop.get("success")
                        else None
                    )
                    if eng2 is not None:
                        statuses.append(eng2)
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
