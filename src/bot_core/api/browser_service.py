"""
bot_core.api.browser_service
----------------------------
BrowserService is now the only public API for browser automation. All legacy wrappers are deprecated.

High-level wrapper around BrowserSession that hides the old
module-level global and can later be re-implemented with Playwright,
a remote Chrome instance, or anything else.

All public methods are coroutine-friendly – call-sites can `await`
them directly.
"""

from __future__ import annotations
from pathlib import Path
import datetime
from typing import Optional
from src.bot_core.settings import settings  # fully typed alias
from src.bot_core.settings import Settings
from .browser_session_api import BrowserSession


class BrowserService:
    def __init__(self, cfg: Settings = settings) -> None:
        self._settings = cfg
        self._session: Optional[BrowserSession] = None

    # ---------- lifecycle ------------------------------------------------
    async def start(
        self,
        url: str | None = None,
        *,
        headless: bool | None = None,
        profile: str | None = None,
    ) -> str:
        """
        Start a browser session.
        Args:
            url: Optional URL to navigate to after startup.
            headless: If set, overrides the config for headless mode.
            profile: Optional Chrome profile name.
        Returns:
            Status message.
        """
        if self._session:
            return "Browser session already started."

        self._session = BrowserSession(profile=profile, headless=headless)

        if not url:
            return "Browser session started."

        # If URL is provided, navigate to it and provide feedback
        actual_url = url
        if not url.startswith(("http://", "https://", "file://", "data:", "about:")):
            actual_url = f"https://{url}"

        try:
            # Navigate to the URL
            await self._session.navigate(actual_url)

            # Get the current URL to show where we navigated to (might be different due to redirects)
            current_url = (
                self._session.get_current_url() if self._session else actual_url
            )

            return f"Browser session started. Navigated to: {current_url}"
        except Exception as e:
            return f"Browser session started, but navigation error: {str(e)}"

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
        """Navigate to a URL and provide feedback on completion.

        Args:
            url: The URL to navigate to

        Returns:
            A message indicating navigation status
        """
        if not self._session:
            return "No active session. Use 'start' first."

        # First send a status that we're navigating
        actual_url = url
        if not url.startswith(("http://", "https://", "file://", "data:", "about:")):
            actual_url = f"https://{url}"

        try:
            # Start navigation
            await self._session.navigate(actual_url)

            # Get the current URL to show where we navigated to (might be different due to redirects)
            current_url = (
                self._session.get_current_url() if self._session else actual_url
            )

            return f"Navigation complete: {current_url}"
        except Exception as e:
            return f"Navigation error: {str(e)}"

    async def screenshot(self, dest: str | None = None) -> tuple[str, str]:
        """Take a screenshot of the current browser view.

        Args:
            dest: Optional destination path for the screenshot.

        Returns:
            A tuple of (file_path, message) where file_path is the full path to the screenshot
            and message is a status message to display.
        """
        if not self._session:
            return "", "No active session. Use 'start' first."
        if dest is None:
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            fname = f"screenshot_{ts}.png"
            browser_download_dir = (
                self._settings.browser_download_dir or "./browser_downloads"
            )
            dest_dir = Path(browser_download_dir)
            dest_path = dest_dir / fname
            dest_str = str(dest_path)
        else:
            dest_str = dest
        assert self._session is not None
        path_str = self._session.screenshot(dest_str)
        return path_str, f"Screenshot saved to {path_str}"


# a default instance for prod code that doesn’t care about DI
default_browser_service = BrowserService()
