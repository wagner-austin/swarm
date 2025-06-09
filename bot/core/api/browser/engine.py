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
        if not self._page:
            raise RuntimeError("Browser not started or page not initialized.")
        await self._page.goto(url, wait_until="load", timeout=self._timeout_ms)

    async def click(self, selector: str) -> None:
        if not self._page:
            raise RuntimeError("Browser not started or page not initialized.")
        await self._page.locator(selector).click(timeout=self._timeout_ms)

    async def fill(self, selector: str, text: str) -> None:
        if not self._page:
            raise RuntimeError("Browser not started or page not initialized.")
        await self._page.locator(selector).fill(text, timeout=self._timeout_ms)

    async def upload(self, selector: str, file_path: Path) -> None:
        if not self._page:
            raise RuntimeError("Browser not started or page not initialized.")
        await self._page.locator(selector).set_input_files(str(file_path))

    async def wait_for(
        self,
        selector: str,
        state: Literal["visible", "hidden", "attached", "detached"] = "visible",
    ) -> None:
        if not self._page:
            raise RuntimeError("Browser not started or page not initialized.")
        await self._page.locator(selector).wait_for(
            state=state, timeout=self._timeout_ms
        )

    async def screenshot(self, dest: Path) -> Path:
        if not self._page:
            raise RuntimeError("Browser not started or page not initialized.")
        await self._page.screenshot(path=str(dest))
        return dest
