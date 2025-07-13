from __future__ import annotations

import datetime
import logging
import os
import uuid
from pathlib import Path
from typing import Literal

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

from bot.browser.ws_logger import WSLogger, jsonl_sink
from bot.core.logger_setup import bind_log_context
from bot.core.service_base import ServiceABC

bind_log_context(service="browser")

logger = logging.getLogger(__name__)


def make_log_path(experiment_id: str, session_id: str, browser_id: str) -> str:
    ts = datetime.datetime.now(datetime.UTC).strftime("%Y%m%d-%H%M%S")
    return os.path.join("logs", experiment_id, session_id, f"{browser_id}-{ts}.jsonl.gz")


class BrowserEngine(ServiceABC):
    """Thin async wrapper around Playwright so the rest of the bot sees *one* surface."""

    def __init__(self, *, headless: bool, proxy: str | None, timeout_ms: int) -> None:
        self._headless = headless
        self._proxy = proxy
        self._timeout_ms = timeout_ms
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._page: Page | None = None
        self._context: BrowserContext | None = None  # Track the browser context to avoid leaks
        self._last_url: str | None = None  # ← track last navigation

    # ------------------------------------------------------------------+
    # Lifecycle                                                        #
    # ------------------------------------------------------------------+
    async def start(self) -> None:
        # Already initialised by WebRunner? → bail out early.
        if self._browser is not None:  # idempotent start()
            if self._page is None:  # but ensure we have a page
                self._page = await self._browser.new_page()
            return

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
            except Exception:
                pass  # Ignore any errors when closing

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
            except Exception:
                page_closed = True

        # At this point we know browser exists because we either had one or created one above
        assert self._browser is not None  # type narrowing for mypy

        if page_closed:
            # Close the previous context if it exists to prevent leaking resources
            if self._context is not None:
                try:
                    await self._context.close()
                except Exception:
                    # Ignore errors when closing, just ensure we don't leak
                    pass

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
                except Exception:
                    # quietly ignore – the caller will surface an error if needed
                    pass

    async def stop(self, *, graceful: bool = True) -> None:
        """Gracefully close all Playwright resources."""
        await self.close()

    def is_running(self) -> bool:
        return self._browser is not None

    def describe(self) -> str:
        return "running" if self.is_running() else "stopped"

    async def close(self) -> None:
        # --- WSLogger shutdown ---
        if getattr(self, "_ws_logger", None) is not None:
            await self._ws_logger.close()
        if self._page:
            await self._page.close()  # Ensure page is closed before context
        if self._context:
            await self._context.close()  # Ensure context is closed before browser
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    # ------------------------------------------------------------------+
    # RPA primitives                                                    #
    # ------------------------------------------------------------------+
    async def goto(self, url: str) -> None:
        await self._ensure_page()
        assert self._page  # type narrowing
        await self._page.goto(url, wait_until="load", timeout=self._timeout_ms)
        self._last_url = url

    async def click(self, selector: str) -> None:
        await self._ensure_page()
        assert self._page is not None  # type narrowing
        await self._page.locator(selector).click(timeout=self._timeout_ms)

    async def fill(self, selector: str, text: str) -> None:
        await self._ensure_page()
        assert self._page is not None  # type narrowing
        await self._page.locator(selector).fill(text, timeout=self._timeout_ms)

    async def upload(self, selector: str, file_path: Path) -> None:
        await self._ensure_page()
        assert self._page is not None  # type narrowing
        await self._page.locator(selector).set_input_files(str(file_path))

    async def wait_for(
        self,
        selector: str,
        state: Literal["visible", "hidden", "attached", "detached"] = "visible",
    ) -> None:
        await self._ensure_page()
        assert self._page is not None  # type narrowing
        await self._page.locator(selector).wait_for(state=state, timeout=self._timeout_ms)

    async def screenshot(self, path: str) -> str:
        """Take a screenshot of the current page and save to the specified path."""
        await self._ensure_page()
        assert self._page is not None  # for mypy
        await self._page.screenshot(path=path)
        return path

    async def health_check(self) -> bool:
        """Perform a minimal health check to ensure browser is alive.
        This is used by the status command to trigger self-healing if needed.
        """
        await self._ensure_page()
        # If we got here without exception, browser is alive or was successfully restored
        return True
