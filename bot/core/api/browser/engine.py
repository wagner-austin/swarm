from __future__ import annotations

from pathlib import Path
from typing import Literal
from playwright.async_api import (
    async_playwright,
    Playwright,
    Browser,
    Page,
)


class BrowserEngine:
    """Thin async wrapper around Playwright so the rest of the bot sees *one* surface."""

    def __init__(self, *, headless: bool, proxy: str | None, timeout_ms: int) -> None:
        self._headless = headless
        self._proxy = proxy
        self._timeout_ms = timeout_ms
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._page: Page | None = None
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
        self._browser = await self._playwright.chromium.launch(
            headless=self._headless,
            timeout=self._timeout_ms,
            proxy={"server": self._proxy} if self._proxy else None,
        )
        self._page = await self._browser.new_page()

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

        self._browser = await self._playwright.chromium.launch(
            headless=self._headless,  # Use the original setting
            timeout=self._timeout_ms,
            proxy={"server": self._proxy} if self._proxy else None,
        )

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
            ctx = (
                self._browser.contexts[0]
                if self._browser.contexts
                else await self._browser.new_context()
            )
            assert ctx is not None  # type narrowing for mypy
            self._page = await ctx.new_page()
            if self._last_url:
                try:
                    await self._page.goto(
                        self._last_url, wait_until="load", timeout=self._timeout_ms
                    )
                except Exception:
                    # quietly ignore – the caller will surface an error if needed
                    pass

    async def close(self) -> None:
        if self._page:
            await self._page.close()  # Ensure page is closed before browser
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
        await self._page.locator(selector).wait_for(
            state=state, timeout=self._timeout_ms
        )

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
