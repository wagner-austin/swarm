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
import tempfile
import logging
import asyncio
from typing import Optional
from bot.core.settings import settings  # fully typed alias
from bot.core.settings import Settings
from .browser import BrowserSession, _normalise_url
from bot.core.validation import looks_like_web_url

logger = logging.getLogger(__name__)


class BrowserService:
    _restart_lock: asyncio.Lock = asyncio.Lock()  # for _ensure_alive

    def __init__(self, cfg: Settings = settings) -> None:
        self._settings = cfg
        self._session: Optional[BrowserSession] = None
        # remember the most recent user preference so automatic restarts
        # stay consistent with what the user last asked for
        self._last_headless: bool = True
        # track the last good page so we can restore it
        self._last_url: str | None = None

    # ---------- lifecycle ------------------------------------------------
    async def start(
        self,
        url: str | None = None,
        *,
        headless: bool | None = None,
        profile: str | None = None,
        timeout: int = 60,
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

        # Determine the effective headless mode
        if headless is None:
            # If no mode is specified by the caller, use the global default setting
            effective_headless = self._settings.browser.headless
            logger.info(
                f"[BrowserService.start] headless param is None. Using global settings.browser.headless: {self._settings.browser.headless}. effective_headless set to: {effective_headless}"
            )
        else:
            # If a mode is specified, use that
            effective_headless = headless
            logger.info(
                f"[BrowserService.start] headless param explicitly set to: {headless}. effective_headless set to: {effective_headless}"
            )

        # Update the last known headless state to what we're actually using
        self._last_headless = effective_headless
        logger.info(
            f"[BrowserService.start] _last_headless updated to: {self._last_headless}. BrowserSession will be initialized with headless={effective_headless}"
        )

        self._session = BrowserSession(
            profile=profile,
            headless=effective_headless,
            timeout=timeout,
        )
        await self._session.initialize()  # awaits the async initialization

        # ── URL sanity-check BEFORE we touch Chrome ────────────────────────
        if url and not looks_like_web_url(url):
            await self.stop()  # tidy up the half-started session
            raise ValueError(
                f"'{url}' doesn't look like a valid web URL "
                "(must be http(s)://example.com)."
            )

        if not url:
            return "Browser session started."

        # If URL is provided, navigate to it and provide feedback
        actual_url = _normalise_url(url)

        try:
            # Navigate to the URL
            await self._session.navigate(actual_url)

            # Get the current URL to show where we navigated to (might be different due to redirects)
            current_url = (
                self._session.get_current_url() if self._session else actual_url
            )
            self._last_url = current_url
            return f"Browser session started. Navigated to: {current_url}"
        except Exception as e:
            logger.exception(
                f"[BrowserService] Failed to start browser session or navigate to '{actual_url}'."
            )
            await self.stop()  # Ensure cleanup if start fails critically
            # Bubble up a more descriptive error, including the original exception type
            raise RuntimeError(
                f"Chrome driver/launch error – {e.__class__.__name__}: {e}"
            ) from e

    async def stop(self) -> str:
        if not self._session:
            return "No active session."
        await self._session.close()
        self._session = None
        return "Browser session stopped."

    async def _ensure_alive(self) -> bool:
        """
        Guarantee a living session.
        Returns True if a restart was required.
        """
        if not self._session or self._session.is_alive():
            return False

        async with self._restart_lock:  # avoid duplicated work
            # Re-check condition inside the lock in case another coroutine fixed it
            if self._session and self._session.is_alive():
                return False

            logger.warning("[Browser] Session dead – auto-restarting…")
            saved_url = self._last_url
            headless = self._last_headless

            await self.stop()
            # Note: self.start() can raise, e.g., if Chrome itself is broken.
            # The caller of _ensure_alive() should be prepared for this.
            await self.start(headless=headless)  # self._last_url is reset by start()

            if (
                saved_url and self._session
            ):  # self._session might be None if start() failed
                try:
                    logger.info(f"[Browser] Attempting to restore URL: {saved_url}")
                    await self._session.navigate(saved_url)
                    self._last_url = saved_url  # Restore _last_url if navigate succeeds
                    logger.info(f"[Browser] Restored {saved_url}")
                except Exception as e:
                    logger.error(f"[Browser] Could not restore {saved_url}: {e}")
                    # _last_url remains None or whatever start() set it to if navigation fails
            elif saved_url:
                logger.warning(
                    f"[Browser] Session not available after restart, cannot restore {saved_url}"
                )

        return True

    # ------------------------------------------------------------------+
    # Public helper                                                     |
    # ------------------------------------------------------------------+
    def set_preferred_headless(self, headless: bool) -> None:
        """Record the user’s preference so the *next* restart honours it."""
        self._last_headless = headless

    # public, used by status
    def alive(self) -> bool:
        return self._session is not None and self._session.is_alive()

    def status(self) -> str:
        # Default mode from settings, used when no session or session is dead
        default_mode_from_settings = (
            "headless" if self._settings.browser.headless else "visible"
        )

        if not self._session:
            return f"No active session (default mode: {default_mode_from_settings})."

        # Mode for an active or last-active session
        current_session_mode = "headless" if self._last_headless else "visible"

        if not self._session.is_alive():
            return (
                f"Session DEAD (Chrome window closed). "
                f"Default mode on restart: {default_mode_from_settings}."
            )
        return f"Current state: {self._session.state.name} (running as: {current_session_mode})."

    # ---------- actions --------------------------------------------------
    async def open(self, url: str) -> str:
        """Navigate to a URL and provide feedback on completion.

        Args:
            url: The URL to navigate to

        Returns:
            A message indicating navigation status
        """
        restarted = await self._ensure_alive()
        if not self._session:
            return "Browser was dead – started a fresh session. Try again 🙂"

        if not looks_like_web_url(url):
            return f"Invalid URL: '{url}'"

        # First send a status that we're navigating
        actual_url = _normalise_url(url)

        try:
            await self._session.navigate(actual_url)
        except Exception as e:  # navigation failed – maybe dead driver
            from selenium.common.exceptions import WebDriverException

            if (
                isinstance(e, WebDriverException)
                and "invalid session id" in str(e).lower()
            ):
                # mark session dead so _ensure_alive() starts a fresh one
                if self._session and self._session.driver:
                    setattr(self._session.driver, "_dead", True)
                await self._ensure_alive()
                if not self._session:
                    return "Browser restarted but still unavailable."
                # retry once
                await self._session.navigate(actual_url)
            else:
                return f"Navigation error: {e}"

        current_url = self._session.get_current_url() if self._session else actual_url
        self._last_url = current_url  # Store after successful navigation
        note = "🔁 (browser had crashed – auto-restarted) " if restarted else ""
        return note + f"Navigation complete: {current_url}"

    async def screenshot(self, dest: str | None = None) -> tuple[str, str]:
        """Take a screenshot of the current browser view.

        Args:
            dest: Optional destination path for the screenshot.

        Returns:
            A tuple of (file_path, message) where file_path is the full path to the screenshot
            and message is a status message to display.
        """
        restarted = await self._ensure_alive()
        if not self._session:
            return "", "Browser was dead – started a fresh session. Try again 🙂"
        if dest is None:
            # Create a temporary file for the screenshot.
            # The file will not be deleted automatically on close (delete=False),
            # so the caller is responsible for deleting it after use.
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_file:
                dest_str = tmp_file.name
            # tmp_file is now closed, but the file still exists at dest_str.
        else:
            dest_str = dest

        assert self._session is not None
        path_str = await self._session.screenshot(dest_str)

        if dest is None:
            message = f"Screenshot saved to temporary file {path_str}. This file should be deleted after use."
        else:
            message = f"Screenshot saved to {path_str}"

        note = "🔁 (browser had crashed – auto-restarted) " if restarted else ""
        return path_str, note + message
