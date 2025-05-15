"""
bot_core.api.browser_service
----------------------------
High-level wrapper around BrowserSession that hides the old
module-level global and can later be re-implemented with Playwright,
a remote Chrome instance, or anything else.

All public methods are coroutine-friendly – call-sites can `await`
them directly.
"""
from __future__ import annotations
import os
import datetime
from typing import Optional
from bot_core.settings import settings
from .browser_session_api import BrowserSession


class BrowserService:
    def __init__(self, cfg=settings):
        self._settings = cfg
        self._session: Optional[BrowserSession] = None

    # ---------- lifecycle ------------------------------------------------
    async def start(self, *, profile: str | None = None,
                    url: str | None = None) -> str:
        if self._session:
            return "Browser session already started."
        self._session = BrowserSession(profile=profile)
        if url:
            await self._session.navigate(url)
        return "Browser session started."

    async def stop(self) -> str:
        if not self._session:
            return "No active session."
        self._session.close()
        self._session = None
        return "Browser session stopped."

    def status(self) -> str:
        if not self._session:
            return "No active session."
        return f"Current state: {self._session.state.name}."

    # ---------- actions --------------------------------------------------
    async def open(self, url: str) -> str:
        if not self._session:
            return "No active session. Use 'start' first."
        await self._session.navigate(url)
        return "Navigating…"

    async def screenshot(self, dest: str | None = None) -> str:
        if not self._session:
            return "No active session. Use 'start' first."
        if dest is None:
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            fname = f"screenshot_{ts}.png"
            dest_dir = self._settings.browser_download_dir
            dest = os.path.join(dest_dir, fname)
        path = self._session.screenshot(dest)
        return f"Screenshot saved to {path}"


# a default instance for prod code that doesn’t care about DI
default_browser_service = BrowserService()
