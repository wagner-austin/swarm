from __future__ import annotations

import asyncio
import concurrent.futures
import datetime
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Awaitable, Callable, Literal, TypeVar

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

from swarm.browser.types import BrowserEngineStatus
from swarm.browser.ws_logger import WSLogger, jsonl_sink
from swarm.core.service_base import ServiceABC

logger = logging.getLogger(__name__)

T = TypeVar("T")


class AsyncRWLock:
    """Writer-preferring readers-writers lock for a single event-loop.

    This lock ensures:
    - Multiple readers can access concurrently
    - Writers get exclusive access
    - Writers are preferred over new readers to prevent starvation
    - All operations are async-safe and won't block the event loop
    """

    def __init__(self) -> None:
        self._readers: int = 0
        self._writer_active: bool = False
        self._writer_waiting: int = 0
        self._cond: asyncio.Condition = asyncio.Condition()

    async def acquire_read(self) -> None:
        """Acquire read lock. Waits if a writer is active or waiting."""
        async with self._cond:
            # Wait while a writer is active or waiting (writer preference)
            await self._cond.wait_for(lambda: not self._writer_active and self._writer_waiting == 0)
            self._readers += 1

    async def release_read(self) -> None:
        """Release read lock. Notifies waiting writers if this was the last reader."""
        async with self._cond:
            self._readers -= 1
            if self._readers == 0:
                self._cond.notify_all()

    async def acquire_write(self) -> None:
        """Acquire write lock. Waits for all readers to finish."""
        async with self._cond:
            self._writer_waiting += 1
            try:
                await self._cond.wait_for(lambda: self._readers == 0 and not self._writer_active)
                self._writer_active = True
            finally:
                self._writer_waiting -= 1

    async def release_write(self) -> None:
        """Release write lock. Notifies all waiting readers and writers."""
        async with self._cond:
            self._writer_active = False
            self._cond.notify_all()


def make_log_path(experiment_id: str, session_id: str, browser_id: str) -> str:
    ts = datetime.datetime.now(datetime.UTC).strftime("%Y%m%d-%H%M%S")
    return os.path.join("logs", experiment_id, session_id, f"{browser_id}-{ts}.jsonl.gz")


class BrowserEngine(ServiceABC):
    """Thin async wrapper around Playwright so the rest of the swarm sees *one* surface."""

    def __init__(self, *, headless: bool, proxy: str | None, timeout_ms: int) -> None:
        self._headless = headless
        self._proxy = proxy
        self._timeout_ms = timeout_ms
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._page: Page | None = None
        self._context: BrowserContext | None = None  # Track the browser context to avoid leaks
        self._last_url: str | None = None  # ← track last navigation
        self._worker_id: str = str(uuid.uuid4())  # Unique identifier for this browser instance
        self._started_at: float = time.time()  # Track when the browser was created
        self._ws_logger: WSLogger | None = None

        # Dedicated background event loop (initialized in start())
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._loop_ready: threading.Event = threading.Event()
        # Async-native RW-lock for concurrent reads and exclusive writes (created on engine loop)
        self._rwlock: AsyncRWLock | None = None

    # ------------------------------------------------------------------+
    # Readers-Writers helpers                                          #
    # ------------------------------------------------------------------+
    async def _run_on_engine_loop(self, coro: Awaitable[T]) -> T:
        """Execute coro in the engine's home loop, regardless of caller thread."""
        if self._loop is None:
            raise RuntimeError("BrowserEngine loop not initialized; call start() first")

        current_loop = asyncio.get_running_loop()
        if current_loop is self._loop:
            # Same loop, run directly
            return await coro
        else:
            # Different loop, proxy to engine's loop
            logger.debug(
                f"Proxying coroutine from loop {id(current_loop)} to engine loop {id(self._loop)}"
            )

            # Wrap the awaitable in a coroutine for run_coroutine_threadsafe
            async def _await_coro() -> T:
                return await coro

            future: concurrent.futures.Future[T] = asyncio.run_coroutine_threadsafe(
                _await_coro(), self._loop
            )
            # Wait for result in caller's loop
            return await asyncio.wrap_future(future)

    def _engine_loop_main(self) -> None:
        """Background thread target: create and run the engine's event loop forever."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._loop_ready.set()
        try:
            loop.run_forever()
        finally:
            try:
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if hasattr(loop, "shutdown_asyncgens"):
                    loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception as exc:
                logger.debug(f"Error during engine loop shutdown: {exc}")
            try:
                loop.close()
            except Exception as exc:
                logger.debug(f"Error closing engine loop: {exc}")

    async def _read_inner(self, fn: Callable[[], Awaitable[T]]) -> T:
        """Acquire a read lock and run the function."""
        if self._rwlock is None:
            raise RuntimeError("BrowserEngine not started")
        await self._rwlock.acquire_read()
        try:
            return await fn()
        finally:
            await self._rwlock.release_read()

    async def _write_inner(self, fn: Callable[[], Awaitable[T]]) -> T:
        """Acquire a write lock and run the function."""
        if self._rwlock is None:
            raise RuntimeError("BrowserEngine not started")
        await self._rwlock.acquire_write()
        try:
            return await fn()
        finally:
            await self._rwlock.release_write()

    async def run_read(self, fn: Callable[[], Awaitable[T]]) -> T:
        """Run *fn* while allowing other readers but blocking writers.

        This is safe for operations that don't modify browser state:
        - screenshot()
        - page.title()
        - page.content()
        """
        # If we're already on the engine's loop, run directly with the lock
        current_loop = asyncio.get_running_loop()
        if self._loop is None or current_loop is self._loop:
            return await self._read_inner(fn)

        # Different loop - need to proxy the entire operation including lock acquisition
        loop = self._loop
        if loop is None or not loop.is_running():
            logger.error("Engine loop is not running for run_read; refusing to proxy")
            raise RuntimeError("BrowserEngine loop not running")

        async def _on_engine_loop() -> T:
            return await self._read_inner(fn)

        # Create the coroutine on the calling loop, then schedule on engine loop
        future: concurrent.futures.Future[T] = asyncio.run_coroutine_threadsafe(
            _on_engine_loop(), loop
        )
        # Wait for result in caller's loop with a timeout guard
        return await asyncio.wait_for(asyncio.wrap_future(future), timeout=30.0)

    async def run_write(self, fn: Callable[[], Awaitable[T]]) -> T:
        """Run *fn* with exclusive access (no other readers or writers).

        This is required for operations that modify browser state:
        - goto()
        - click()
        - fill()
        - navigation

        NOTE: Lock held for entire browser operation; acceptable while writer volume is low.
        Future optimization: release lock after DOM mutation, await I/O outside lock.
        """
        # If we're already on the engine's loop, run directly with the lock
        current_loop = asyncio.get_running_loop()
        if self._loop is None or current_loop is self._loop:
            return await self._write_inner(fn)

        # Different loop - need to proxy the entire operation including lock acquisition
        loop = self._loop
        if loop is None or not loop.is_running():
            logger.error("Engine loop is not running for run_write; refusing to proxy")
            raise RuntimeError("BrowserEngine loop not running")

        async def _on_engine_loop() -> T:
            return await self._write_inner(fn)

        # Create the coroutine on the calling loop, then schedule on engine loop
        future: concurrent.futures.Future[T] = asyncio.run_coroutine_threadsafe(
            _on_engine_loop(), loop
        )
        # Wait for result in caller's loop with a timeout guard
        return await asyncio.wait_for(asyncio.wrap_future(future), timeout=30.0)

    # ------------------------------------------------------------------+
    # Lifecycle                                                        #
    # ------------------------------------------------------------------+
    async def start(self) -> None:
        """Start the engine with a dedicated background event loop thread.

        Idempotent: safe to call multiple times.
        """
        # Start loop thread if needed
        if self._loop_thread is None or self._loop is None or not self._loop_ready.is_set():
            self._loop_ready.clear()
            self._loop_thread = threading.Thread(
                target=self._engine_loop_main,
                name=f"BrowserEngineLoop-{self._worker_id}",
                daemon=True,
            )
            self._loop_thread.start()
            if not self._loop_ready.wait(timeout=5.0):
                raise RuntimeError("Timed out waiting for BrowserEngine loop thread to start")

        # Initialize browser on the engine loop (idempotent)
        await self._run_on_engine_loop(self._start_browser())

    async def _start_browser(self) -> None:
        # Initialize lock on first start (engine loop already set by loop thread)
        if self._rwlock is None:
            self._rwlock = AsyncRWLock()

        # Already initialised by WebRunner? → bail out early.
        if self._browser is not None:  # idempotent start()
            if self._page is None:  # but ensure we have a page
                self._page = await self._browser.new_page()
            return

        self._started_at = time.time()
        self._playwright = await async_playwright().start()
        assert self._playwright is not None  # mypy: narrows to Playwright
        try:
            display = os.getenv("DISPLAY")
            logger.info(
                "Launching Chromium (headless=%s, DISPLAY=%s) in BrowserEngine.start",
                self._headless,
                display,
            )
            self._browser = await self._playwright.chromium.launch(
                headless=self._headless,
                timeout=self._timeout_ms,
                proxy={"server": self._proxy} if self._proxy else None,
            )
        except Exception as exc:
            logger.exception("Browser launch failed in start()", exc_info=exc)
            raise
        self._page = await self._browser.new_page()

        # Set reasonable timeouts to prevent blocking workers
        # 10 seconds for navigation, 5 seconds for element actions
        self._page.set_default_navigation_timeout(10000)
        self._page.set_default_timeout(5000)

        # --- WSLogger integration ---
        browser_id = uuid.uuid4().hex
        session_id = os.environ.get("SESSION_ID", uuid.uuid4().hex)
        episode_id = uuid.uuid4().hex
        experiment_id = os.environ.get("EXPERIMENT_ID", "default-exp")
        protocol_version = os.environ.get("GIT_COMMIT", "unknown")
        log_path = make_log_path(experiment_id, session_id, browser_id)
        sink = await jsonl_sink(log_path, gzip_compress=True)
        self._ws_logger = await WSLogger(
            browser_id=browser_id,
            session_id=session_id,
            episode_id=episode_id,
            experiment_id=experiment_id,
            protocol_version=protocol_version,
            sink=sink,
        ).__aenter__()
        await self._ws_logger.attach(self._page)

    # ------------------------------------------------------------------+
    # Self-healing helpers                                            #
    # ------------------------------------------------------------------+
    async def _restart_browser(self) -> None:
        """Create a fresh Chromium instance with the *original* headless flag."""
        if self._playwright is None:
            self._playwright = await async_playwright().start()

        # Shut anything that might still linger (defensive)
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception as exc:
                logger.warning(f"Error closing browser during restart: {exc}")

        try:
            import os

            display = os.getenv("DISPLAY")
            logger.info(
                "Launching Chromium (headless=%s, DISPLAY=%s) in _restart_browser",
                self._headless,
                display,
            )
            self._browser = await self._playwright.chromium.launch(
                headless=self._headless,  # Use the original setting
                timeout=self._timeout_ms,
                proxy={"server": self._proxy} if self._proxy else None,
            )
        except Exception as exc:
            logger.exception("Browser launch failed in _restart_browser", exc_info=exc)
            raise

    # ------------------------------------------------------------+
    # internal – ensure we have an open page                      |
    # ------------------------------------------------------------+
    async def _ensure_page(self) -> None:
        """
        Re‑open a page (and context if needed) when the user closed the tab.
        Restores the last visited URL if we know it.
        """
        # Check if browser needs to be recreated
        if self._browser is None:
            await self._restart_browser()

        # Check if page is None or has been closed
        page_closed = self._page is None
        if not page_closed and self._page is not None:
            try:
                # Using evaluate() to safely check page status without type errors
                # If this fails, page is likely closed
                await self._page.evaluate("1")
            except Exception as exc:
                logger.debug(f"Page evaluation failed, marking as closed: {exc}")
                page_closed = True

        # At this point we know browser exists because we either had one or created one above
        assert self._browser is not None  # type narrowing for mypy

        if page_closed:
            # Close the previous context if it exists to prevent leaking resources
            if self._context is not None:
                try:
                    await self._context.close()
                except Exception as exc:
                    # Log but don't fail - this is cleanup
                    logger.warning(f"Error closing browser context during cleanup: {exc}")

            # Create a new context
            ctx = await self._browser.new_context()
            assert ctx is not None  # type narrowing for mypy
            self._context = ctx  # Save the context reference to close it later

            # Create a new page in the context
            self._page = await ctx.new_page()
            if self._last_url:
                try:
                    await self._page.goto(
                        self._last_url, wait_until="load", timeout=self._timeout_ms
                    )
                except Exception as exc:
                    # Log navigation failure - caller will handle if needed
                    logger.debug(
                        f"Failed to navigate to last URL {self._last_url} after page recreation: {exc}"
                    )

    async def stop(self, *, graceful: bool = True) -> None:
        """Gracefully close all Playwright resources."""
        await self.close()

    def is_running(self) -> bool:
        return self._browser is not None

    def describe(self) -> str:
        return "running" if self.is_running() else "stopped"

    async def close(self) -> None:
        async def _close_inner() -> None:
            # --- WSLogger shutdown ---
            ws_logger = self._ws_logger
            if ws_logger is not None:
                try:
                    await ws_logger.close()
                except Exception as exc:
                    logger.warning(f"Error closing WSLogger: {exc}")
                self._ws_logger = None
            if self._page:
                try:
                    await self._page.close()
                except Exception as exc:
                    logger.warning(f"Error closing page: {exc}")
                self._page = None
            if self._context:
                try:
                    await self._context.close()
                except Exception as exc:
                    logger.warning(f"Error closing context: {exc}")
                self._context = None
            if self._browser:
                try:
                    await self._browser.close()
                except Exception as exc:
                    logger.warning(f"Error closing browser: {exc}")
                self._browser = None
            if self._playwright:
                try:
                    await self._playwright.stop()
                except Exception as exc:
                    logger.warning(f"Error stopping Playwright: {exc}")
                self._playwright = None

        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None
        if self._loop is not None and current_loop is not self._loop:
            await self._run_on_engine_loop(_close_inner())
        else:
            await _close_inner()

        if self._loop is not None:
            try:
                self._loop.call_soon_threadsafe(self._loop.stop)
            except Exception as exc:
                logger.debug(f"Error submitting loop.stop(): {exc}")
        if self._loop_thread is not None and threading.current_thread() is not self._loop_thread:
            try:
                self._loop_thread.join(timeout=5.0)
            except Exception as exc:
                logger.debug(f"Error joining loop thread: {exc}")
        self._loop_thread = None
        self._loop = None
        self._loop_ready.clear()

    # ------------------------------------------------------------------+
    # RPA primitives                                                    #
    # ------------------------------------------------------------------+
    async def goto(self, url: str) -> None:
        async def _navigate() -> None:
            await self._ensure_page()
            page = self._page
            assert page is not None  # type narrowing
            await page.goto(url, wait_until="load", timeout=self._timeout_ms)
            self._last_url = url

        await self.run_write(_navigate)

    async def click(self, selector: str, *, no_wait_after: bool = False) -> None:
        async def _click() -> None:
            await self._ensure_page()
            page = self._page
            assert page is not None  # type narrowing
            # When clicking links that navigate off-site, Playwright will wait for navigation
            # unless no_wait_after=True is specified. Expose this to callers to avoid
            # environment-dependent delays (e.g., CI egress slowness).
            await page.locator(selector).click(
                timeout=self._timeout_ms, no_wait_after=no_wait_after
            )

        await self.run_write(_click)

    async def fill(self, selector: str, text: str) -> None:
        async def _fill() -> None:
            await self._ensure_page()
            page = self._page
            assert page is not None  # type narrowing
            await page.locator(selector).fill(text, timeout=self._timeout_ms)

        await self.run_write(_fill)

    async def upload(self, selector: str, file_path: Path) -> None:
        async def _upload() -> None:
            await self._ensure_page()
            page = self._page
            assert page is not None  # type narrowing
            await page.locator(selector).set_input_files(str(file_path))

        await self.run_write(_upload)

    async def wait_for(
        self,
        selector: str,
        state: Literal["visible", "hidden", "attached", "detached"] = "visible",
    ) -> None:
        async def _wait() -> None:
            await self._ensure_page()
            page = self._page
            assert page is not None  # type narrowing
            await page.locator(selector).wait_for(state=state, timeout=self._timeout_ms)

        await self.run_write(_wait)

    async def screenshot(self, path: str) -> str:
        """Take a screenshot of the current page and save to the specified path."""
        import time as time_module

        start_time = time_module.time()
        logger.debug(f"screenshot() called for path={path}")

        # Ensure the page exists (writer path) before taking a read-only screenshot
        async def _ensure() -> None:
            ensure_start = time_module.time()
            logger.debug("screenshot: calling _ensure_page()")
            await self._ensure_page()
            ensure_elapsed = time_module.time() - ensure_start
            logger.debug(f"screenshot: _ensure_page() took {ensure_elapsed:.2f}s")

        write_start = time_module.time()
        await self.run_write(_ensure)
        write_elapsed = time_module.time() - write_start
        logger.debug(f"screenshot: run_write(_ensure) took {write_elapsed:.2f}s")

        page = self._page
        assert page is not None  # type narrowing

        async def _take_screenshot() -> None:
            shot_start = time_module.time()
            logger.debug("screenshot: calling page.screenshot()")
            await page.screenshot(path=path)
            shot_elapsed = time_module.time() - shot_start
            logger.debug(f"screenshot: page.screenshot() took {shot_elapsed:.2f}s")

        read_start = time_module.time()
        await self.run_read(_take_screenshot)
        read_elapsed = time_module.time() - read_start
        logger.debug(f"screenshot: run_read(_take_screenshot) took {read_elapsed:.2f}s")

        total_elapsed = time_module.time() - start_time
        logger.debug(f"screenshot() completed in {total_elapsed:.2f}s")
        return path

    async def health_check(self) -> bool:
        """Perform a minimal health check to ensure browser is alive.
        This is used by the status command to trigger self-healing if needed.
        """

        async def _check() -> bool:
            await self._ensure_page()
            # If we got here without exception, browser is alive or was successfully restored
            return True

        return await self.run_write(_check)

    async def status(self) -> BrowserEngineStatus:
        """Get the current status of the browser engine.

        Returns a dictionary with browser state information.
        This method is called by the /status Discord command.
        """
        try:
            # Perform health check first
            is_healthy = await self.health_check()

            async def _get_status() -> BrowserEngineStatus:
                return {
                    "worker_id": self._worker_id,
                    "status": "healthy" if is_healthy else "unhealthy",
                    "browser_active": self._browser is not None,
                    "page_active": self._page is not None,
                    "url": self._page.url if self._page else None,
                    "sessions": 1 if self._page else 0,  # For compatibility with fake
                    "uptime": time.time() - self._started_at,
                }

            return await self.run_read(_get_status)
        except Exception as e:
            logger.error(f"Error getting browser status: {e}")
            return {
                "worker_id": self._worker_id,
                "status": "error",
                "error": str(e),
                "browser_active": False,
                "page_active": False,
                "sessions": 0,
                "url": None,
                "uptime": 0.0,
            }
