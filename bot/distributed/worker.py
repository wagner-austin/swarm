"""
Generic Distributed Worker Entrypoint
====================================
Consumes jobs from the broker and dynamically dispatches them to the correct handler
(browser, tankpit, etc). Designed for multi-instance distributed operation.

ARCHITECTURAL GUIDELINE (CRITICAL):
-----------------------------------
For all dynamic dispatch (e.g., getattr(...)(*args, **kwargs)) in distributed job handlers:
- ALWAYS filter kwargs using filter_kwargs_for_method before calling the method. This prevents runtime TypeErrors and test assertion errors due to extra job metadata (like session_id, close_session) leaking into engine methods.
- ALWAYS perform session cleanup (stop/close) if close_session is set, EVEN IF the method does not exist. This ensures resources are freed and tests remain robust.
- This pattern must be enforced in both production and tests to prevent regressions and reduce test flakiness.

Usage:
    poetry run python -m bot.distributed.worker \
        --redis-url=redis://localhost:6379/0 \
        --worker-id=worker-1 \
        [--job-type-prefix=browser.]

Environment variables (fallback):
    REDIS_URL, WORKER_ID, JOB_TYPE_PREFIX

All new code is type-annotated and includes docstrings.
"""

import argparse
import asyncio
import inspect
import logging
import os
import signal
from typing import Any, Awaitable, Callable, Dict, Optional

# Import local runtimes/engines for dispatch
from bot.browser.engine import BrowserEngine
from bot.browser.runtime import BrowserRuntime  # If still needed elsewhere
from bot.distributed.broker import Broker
from bot.distributed.model import Job
from bot.infra.tankpit.engine import TankPitEngine
from bot.utils.dispatch import filter_kwargs_for_method

logger = logging.getLogger("worker")
logging.basicConfig(level=logging.INFO)

HandlerFunc = Callable[[Job], Awaitable[Any]]


class Worker:
    """
    Generic distributed worker that consumes jobs from the broker
    and dispatches them to registered handlers based on job type.
    """

    def __init__(
        self,
        broker: Broker,
        worker_id: str,
        job_type_prefix: str | None = None,
        settings: Any | None = None,
    ) -> None:
        self.broker = broker
        self.worker_id = worker_id
        self.job_type_prefix = job_type_prefix
        self.handlers: dict[str, HandlerFunc] = {}
        self.settings = settings
        self._shutdown = asyncio.Event()

    def register_handler(self, prefix: str, handler: HandlerFunc) -> None:
        """Register a handler function for a job type prefix (e.g., 'browser.')."""
        self.handlers[prefix] = handler

    async def run(self) -> None:
        logger.info(f"Worker {self.worker_id} starting. Listening for jobs.")
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._shutdown.set)

        while not self._shutdown.is_set():
            try:
                job = await self.broker.consume(
                    group=self.job_type_prefix or "all-workers",
                    consumer=self.worker_id,
                )
            except TimeoutError:
                continue
            except Exception as exc:
                logger.error(f"Error consuming job: {exc}")
                await asyncio.sleep(1)
                continue
            if self.job_type_prefix and not job.type.startswith(self.job_type_prefix):
                continue  # Not for this worker
            await self.dispatch(job)

    async def dispatch(self, job: Job) -> None:
        """Dispatch the job to the appropriate handler based on its type prefix."""
        for prefix, handler in self.handlers.items():
            if job.type.startswith(prefix):
                logger.info(f"Dispatching job {job.type} to handler {prefix}")
                try:
                    await handler(job)
                except Exception as exc:
                    logger.error(f"Handler error for job {job.type}: {exc}")
                return
        logger.warning(f"No handler registered for job type: {job.type}")


# --- Multi-engine-per-worker: session-keyed runtime/engine maps ---

_browser_engines: dict[str, BrowserEngine] = {}
_tankpit_engines: dict[str, TankPitEngine] = {}


async def cleanup_browser_session(session_id: str) -> None:
    """Close and remove a browser engine session by session_id."""
    engine = _browser_engines.pop(session_id, None)
    if engine:
        try:
            await engine.stop(graceful=True)
            logger.info(f"[Browser:{session_id}] Session closed and cleaned up.")
        except Exception as exc:
            logger.exception(f"[Browser:{session_id}] Error during cleanup: {exc}")


async def cleanup_tankpit_session(session_id: str) -> None:
    """Close and remove a tankpit engine session by session_id."""
    engine = _tankpit_engines.pop(session_id, None)
    if engine:
        try:
            await engine.stop(graceful=True)
            logger.info(f"[Tankpit:{session_id}] Session closed and cleaned up.")
        except Exception as exc:
            logger.exception(f"[Tankpit:{session_id}] Error during cleanup: {exc}")


async def close_all_sessions() -> None:
    """Gracefully close all browser and tankpit sessions for shutdown."""
    for session_id in list(_browser_engines.keys()):
        await cleanup_browser_session(session_id)
    for session_id in list(_tankpit_engines.keys()):
        await cleanup_tankpit_session(session_id)
    logger.info("All browser and tankpit sessions closed.")


async def handle_browser_job(job: Job) -> None:
    """
    Handle browser jobs using BrowserEngine.
    Each job is dispatched to a session-specific engine instance, keyed by session_id.
    If job.kwargs['close_session'] is True, the session is closed after the job.
    """
    session_id = str(job.kwargs.get("session_id") or job.reply_to or job.id)
    engine = _browser_engines.get(session_id)
    if engine is None:
        engine = BrowserEngine(headless=True, proxy=None, timeout_ms=60000)
        await engine.start()
        _browser_engines[session_id] = engine
    method_name = job.type.removeprefix("browser.")
    method = getattr(engine, method_name, None)
    if not method or not callable(method):
        logger.error(f"No such browser method: {method_name}")
        if job.kwargs.get("close_session"):
            await cleanup_browser_session(session_id)
        return
    try:
        filtered_kwargs = filter_kwargs_for_method(method, job.kwargs)
        logger.info(f"[Browser:{session_id}] {method_name}(*{job.args}, **{filtered_kwargs})")
        result = await method(*job.args, **filtered_kwargs)
        logger.info(f"[Browser:{session_id}] Result: {result}")
    except Exception as exc:
        logger.exception(f"[Browser:{session_id}] Error executing {method_name}: {exc}")
    if job.kwargs.get("close_session"):
        await cleanup_browser_session(session_id)


async def handle_tankpit_job(job: Job) -> None:
    """
    Handle tankpit jobs using TankPitEngine.
    Each job is dispatched to a session-specific engine instance, keyed by session_id.
    If job.kwargs['close_session'] is True, the session is closed after the job.
    """
    session_id = str(job.kwargs.get("session_id") or job.reply_to or job.id)
    engine = _tankpit_engines.get(session_id)
    if engine is None:
        q_in: asyncio.Queue[tuple[str, bytes]] = asyncio.Queue()
        q_out: asyncio.Queue[bytes] = asyncio.Queue()
        engine = TankPitEngine(q_in, q_out)
        await engine.start()
        _tankpit_engines[session_id] = engine
    method_name = job.type.removeprefix("tankpit.")
    method = getattr(engine, method_name, None)
    if not method or not callable(method):
        logger.error(f"No such tankpit method: {method_name}")
        if job.kwargs.get("close_session"):
            await cleanup_tankpit_session(session_id)
        return
    try:
        filtered_kwargs = filter_kwargs_for_method(method, job.kwargs)
        logger.info(f"[Tankpit:{session_id}] {method_name}(*{job.args}, **{filtered_kwargs})")
        result = await method(*job.args, **filtered_kwargs)
        logger.info(f"[Tankpit:{session_id}] Result: {result}")
    except Exception as exc:
        logger.exception(f"[Tankpit:{session_id}] Error executing {method_name}: {exc}")
    if job.kwargs.get("close_session"):
        await cleanup_tankpit_session(session_id)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Distributed Worker Entrypoint")
    parser.add_argument(
        "--redis-url", type=str, default=os.getenv("REDIS_URL", "redis://localhost:6379/0")
    )
    parser.add_argument("--worker-id", type=str, default=os.getenv("WORKER_ID", "worker-1"))
    parser.add_argument("--job-type-prefix", type=str, default=os.getenv("JOB_TYPE_PREFIX", None))
    return parser.parse_args()


async def _cleanup_orphaned_browsers() -> None:
    """
    Best-effort cleanup of orphaned Playwright/Chromium processes from previous crashes.
    Only runs on startup. Platform-aware: only works on POSIX and if psutil is available.
    """
    import logging
    import os
    import subprocess
    import sys

    logger = logging.getLogger(__name__)
    try:
        # Only attempt on POSIX (Linux, macOS)
        if os.name != "posix":
            return
        # Try to find orphaned Chromium/Playwright browser processes
        # This is a best effort using 'pkill' or 'ps'
        # (You may want to tune this for your deployment)
        for proc_name in ["chromium", "chrome", "playwright"]:
            try:
                subprocess.run(["pkill", "-f", proc_name], check=False)
            except Exception:
                pass  # Don't crash if pkill not available
        logger.info("Best-effort orphaned browser cleanup attempted.")
    except Exception as exc:
        logger.warning(f"Could not clean up orphaned browser processes: {exc}")


async def main() -> None:
    args = parse_args()
    await _cleanup_orphaned_browsers()  # Clean up orphans before starting any engines
    broker = Broker(args.redis_url)
    worker = Worker(broker, worker_id=args.worker_id, job_type_prefix=args.job_type_prefix)
    # Register dynamic handlers
    worker.register_handler("browser.", handle_browser_job)
    worker.register_handler("tankpit.", handle_tankpit_job)

    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("Shutdown signal received. Cleaning up all sessions...")
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # add_signal_handler may not be available on Windows
            signal.signal(sig, lambda *_: shutdown_event.set())

    async def _run_and_cleanup() -> None:
        try:
            await worker.run()
        finally:
            await close_all_sessions()
            logger.info("Worker shutdown complete. All sessions cleaned up.")

    # Run worker and cleanup on shutdown
    await asyncio.gather(_run_and_cleanup(), shutdown_event.wait())


if __name__ == "__main__":
    asyncio.run(main())
