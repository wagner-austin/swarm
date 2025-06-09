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
from .browser import BrowserSession
from .browser.exceptions import (
    BrowserInitializationError,
    InvalidURLError,
    NavigationError,  # Add other exceptions as they are used
    BrowserStateError,
    ScreenshotError,
)
from bot.utils.urls import (
    looks_like_web_url,
    normalise as _normalise_url,
)  # Corrected import paths

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
        logger.info(
            f"[BrowserService.start] Called with URL: {url}, headless: {headless}, profile: {profile}, timeout: {timeout}"
        )
        if self._session:
            logger.info("[BrowserService.start] Session already active.")
            return "Browser session already started."

        # Determine the effective headless mode
        if headless is None:
            # If no mode is specified by the caller, use the global default setting
            effective_headless = self._settings.browser.headless
            logger.debug(
                f"[BrowserService.start] Headless mode not specified, using default from settings: {effective_headless}"
            )
        else:
            # If a mode is specified, use that
            effective_headless = headless
            logger.debug(
                f"[BrowserService.start] Headless mode explicitly set to: {effective_headless}"
            )

        # Update the last known headless state to what we're actually using
        self._last_headless = effective_headless
        logger.debug(
            f"[BrowserService.start] Stored preference _last_headless updated to: {self._last_headless}"
        )

        logger.info(
            f"[BrowserService.start] Initializing BrowserSession with profile='{profile}', headless={effective_headless}, timeout={timeout}s."
        )
        self._session = BrowserSession(
            profile=profile,
            headless=effective_headless,
            timeout=timeout,
        )
        try:
            logger.info("[BrowserService.start] Calling BrowserSession.initialize().")
            await self._session.initialize()  # awaits the async initialization
            logger.info("[BrowserService.start] BrowserSession.initialize() completed.")
        except BrowserInitializationError as e:
            logger.error(
                f"[BrowserService.start] BrowserSession.initialize() failed: {e}",
                exc_info=True,
            )
            self._session = None  # Ensure session is None if init fails
            raise  # Re-raise the specific error caught from session.initialize()

        # ── URL sanity-check BEFORE we touch Chrome ────────────────────────
        if url and not looks_like_web_url(url):
            await self.stop()  # tidy up the half-started session
            raise InvalidURLError(
                f"'{url}' doesn't look like a valid web URL "
                "(must be http(s)://example.com)."
            )

        if not url:
            logger.info(
                "[BrowserService.start] Browser session started without an initial URL navigation."
            )
            return "Browser session started."

        # If URL is provided, navigate to it and provide feedback
        actual_url = _normalise_url(url)
        logger.info(f"[BrowserService.start] Navigating to initial URL: {actual_url}")
        try:
            # Navigate to the URL
            await self._session.navigate(actual_url)

            # Get the current URL to show where we navigated to (might be different due to redirects)
            current_url = (
                self._session.get_current_url() if self._session else actual_url
            )
            self._last_url = current_url
            logger.info(
                f"[BrowserService.start] Successfully started and navigated to: {current_url}"
            )
            return f"Browser session started. Navigated to: {current_url}"
        except NavigationError as e:
            logger.error(
                f"[BrowserService.start] Initial navigation to '{actual_url}' failed: {e}",
                exc_info=True,
            )
            await self.stop()  # Ensure cleanup
            raise BrowserInitializationError(
                f"Failed to navigate to initial URL '{actual_url}': {e}"
            ) from e  # Wrap as init error
        except Exception as e:  # Catch any other unexpected errors during start sequence after session init
            logger.exception(
                f"[BrowserService] Failed to start browser session or navigate to '{actual_url}'."
            )
            await self.stop()  # Ensure cleanup if start fails critically
            # Bubble up a more descriptive error, including the original exception type
            raise BrowserInitializationError(
                f"Unexpected error during browser start sequence for URL '{actual_url}': {e.__class__.__name__} - {e}"
            ) from e

    async def stop(self) -> str:
        logger.info("[BrowserService.stop] Called.")
        if self._session:
            logger.info(
                "[BrowserService.stop] Active session found, attempting to close."
            )
            try:
                await self._session.close()
                logger.info("[BrowserService.stop] BrowserSession.close() completed.")
            except Exception as e:
                logger.error(
                    f"[BrowserService.stop] Error during BrowserSession.close(): {e}",
                    exc_info=True,
                )
                # Still attempt to clear the session reference
            finally:
                self._session = None
                self._last_url = None  # Clear last URL on stop
                logger.info(
                    "[BrowserService.stop] Session cleared. Browser session stopped."
                )
            return "Browser session stopped."
        else:
            logger.info("[BrowserService.stop] No active browser session to stop.")
            return "No active browser session to stop."

    async def _ensure_alive(self) -> bool:
        """
        Guarantee a living session.
        Returns True if a restart was required.
        """
        logger.debug("[BrowserService._ensure_alive] Checking session status.")
        # Check if session exists and is alive
        if self._session and self._session.is_alive():
            logger.debug(
                "[BrowserService._ensure_alive] Session exists and is alive. No action needed."
            )
            return False  # No restart needed

        logger.info(
            "[BrowserService._ensure_alive] Session is dead or not initialized. Attempting to (re)start."
        )
        async with self._restart_lock:  # avoid duplicated work
            # Double-check after acquiring the lock, in case another coroutine fixed it
            if self._session and self._session.is_alive():
                logger.debug(
                    "[BrowserService._ensure_alive] Session was revived by another coroutine while waiting for lock. No action needed."
                )
                return False

            logger.info(
                "[BrowserService._ensure_alive] Acquired lock. Proceeding with session (re)start."
            )

            # If there was an old, dead session, it's already handled by self.stop() called within self.start()
            # or if self.start() is called directly. However, the original logic explicitly called self.stop() here.
            # The new self.start() handles its own session setup, including stopping an existing one if necessary.
            # The self.stop() call here was primarily to clear the old _session object before calling start().
            # Let's ensure the old session is cleared if it exists, then call start.
            if (
                self._session
            ):  # If there's a reference to an old (presumably dead) session object
                logger.info(
                    "[BrowserService._ensure_alive] Clearing reference to old/dead session object before attempting restart."
                )
                # We don't need to call self._session.close() again if self.start() will do it,
                # but explicitly setting self._session to None ensures start begins fresh if it doesn't stop first.
                # However, self.start() *does* check `if self._session:` and returns if it's active.
                # To force a restart, we must clear self._session or ensure self.start() knows it's a restart.
                # The simplest is to call self.stop() to ensure a clean slate, which also clears self._session.
                logger.info(
                    "[BrowserService._ensure_alive] Calling self.stop() to ensure clean state before restart."
                )
                await self.stop()  # This will set self._session to None.

            # Attempt to restart the session using the last known URL and headless mode
            logger.info(
                f"[BrowserService._ensure_alive] Attempting to (re)start session with last_url='{self._last_url}', last_headless={self._last_headless}."
            )
            try:
                # self.start() has comprehensive logging and will use self._last_url and self._last_headless if url/headless are None.
                await self.start(
                    url=self._last_url,
                    headless=self._last_headless,
                )
                # If start succeeds, self._session will be populated and self._last_url potentially updated.
                if self._session and self._session.is_alive():
                    logger.info(
                        "[BrowserService._ensure_alive] Browser session (re)started successfully."
                    )
                    return True  # Restart was performed
                else:
                    logger.error(
                        "[BrowserService._ensure_alive] self.start() completed but session is not alive or not set."
                    )
                    self._session = None  # Ensure consistent state
                    return False  # Restart effectively failed
            except Exception as e:
                # self.start() should log its own failures, but we log the failure of _ensure_alive here.
                logger.error(
                    f"[BrowserService._ensure_alive] Call to self.start() failed during (re)start attempt: {e}",
                    exc_info=True,
                )
                self._session = None  # Ensure session is None if restart fails
                return False  # Restart failed
        # Lock released automatically

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
        logger.info(f"[BrowserService.open] Called with URL: '{url}'")
        """Navigate to a URL and provide feedback on completion.

        Args:
            A message indicating navigation status
        """
        logger.debug("[BrowserService.open] Ensuring session is alive.")
        restarted = await self._ensure_alive()
        if restarted:
            logger.info("[BrowserService.open] Session was restarted by _ensure_alive.")
        else:
            logger.debug("[BrowserService.open] Session was already alive.")

        if not self._session:
            # This case should ideally be rare if _ensure_alive works correctly and raises or fixes.
            logger.error(
                "[BrowserService.open] Session is None even after _ensure_alive. Cannot open URL."
            )
            # Consider raising BrowserStateError if stricter error handling is desired in the future.
            return "Browser was dead or could not be started. Try again 🙂"

        if not looks_like_web_url(url):
            logger.warning(f"[BrowserService.open] Invalid URL format: '{url}'")
            raise InvalidURLError(f"Invalid URL: '{url}'")

        # First send a status that we're navigating
        actual_url = _normalise_url(url)
        logger.info(
            f"[BrowserService.open] Attempting to navigate to normalized URL: '{actual_url}'"
        )
        try:
            await self._session.navigate(actual_url)
        except Exception as e:  # navigation failed – maybe dead driver
            from selenium.common.exceptions import WebDriverException

            # unwrap our own wrapper so auto-revive still kicks in
            underlying = e.__cause__ or e
            if (
                isinstance(underlying, WebDriverException)
                and "invalid session id" in str(underlying).lower()
            ):
                # mark session dead so _ensure_alive() starts a fresh one
                logger.warning(
                    f"[BrowserService.open] WebDriverException with 'invalid session id' detected for URL '{actual_url}'. Attempting recovery."
                )
                if self._session and self._session.driver:
                    setattr(
                        self._session.driver, "_dead", True
                    )  # Mark as dead for _ensure_alive's logic

                logger.info(
                    "[BrowserService.open] Calling _ensure_alive to recover from invalid session id."
                )
                recovery_restarted = await self._ensure_alive()
                if not self._session:
                    logger.error(
                        "[BrowserService.open] Recovery failed: Session still None after _ensure_alive."
                    )
                    # This return is kept for now, but raising NavigationError might be more consistent.
                    return "Browser restarted due to an issue but is still unavailable."

                logger.info(
                    f"[BrowserService.open] Recovery attempt: Retrying navigation to '{actual_url}'. Restarted during recovery: {recovery_restarted}"
                )
                try:
                    await self._session.navigate(actual_url)
                    logger.info(
                        f"[BrowserService.open] Successfully navigated to '{actual_url}' after recovery."
                    )
                except Exception as retry_e:
                    logger.error(
                        f"[BrowserService.open] Navigation to '{actual_url}' failed even after recovery and retry: {retry_e}",
                        exc_info=True,
                    )
                    raise NavigationError(
                        f"Navigation to '{actual_url}' failed after retry: {retry_e.__class__.__name__} - {retry_e}"
                    ) from retry_e
            else:
                logger.error(
                    f"[BrowserService.open] Navigation error for URL '{actual_url}': {e}",
                    exc_info=True,
                )
                raise NavigationError(
                    f"Navigation error for '{actual_url}': {e.__class__.__name__} - {e}"
                ) from e

        current_url = self._session.get_current_url() if self._session else actual_url
        self._last_url = current_url  # Store after successful navigation
        note = (
            "🔁 (browser had crashed – auto-restarted by initial _ensure_alive) "
            if restarted
            else ""
        )
        logger.info(
            f"[BrowserService.open] {note}Navigation complete. Current URL: '{current_url}'"
        )
        return note + f"Navigation complete: {current_url}"

    async def screenshot(self, dest: str | None = None) -> tuple[str, str]:
        logger.info(
            f"[BrowserService.screenshot] Called with destination: '{dest if dest else 'temporary file'}'"
        )
        """Take a screenshot of the current browser view.

        Args:
            dest: Optional destination path for the screenshot.

        Returns:
            A tuple of (file_path, message) where file_path is the full path to the screenshot
            and message is a status message to display.
        """
        logger.debug("[BrowserService.screenshot] Ensuring session is alive.")
        restarted = await self._ensure_alive()
        if restarted:
            logger.info(
                "[BrowserService.screenshot] Session was restarted by _ensure_alive."
            )
        else:
            logger.debug("[BrowserService.screenshot] Session was already alive.")

        if not self._session:
            logger.error(
                "[BrowserService.screenshot] Session is None even after _ensure_alive. Cannot take screenshot."
            )
            raise BrowserStateError(
                "Browser session not available, cannot take screenshot."
            )

        if dest is None:
            logger.debug(
                "[BrowserService.screenshot] No destination path provided, creating temporary file."
            )
            # Create a temporary file for the screenshot.
            # The file will not be deleted automatically on close (delete=False),
            # so the caller is responsible for deleting it after use.
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_file:
                dest_str = tmp_file.name
            # tmp_file is now closed, but the file still exists at dest_str.
        else:
            dest_str = dest

        assert self._session is not None  # Should be guaranteed by the check above
        logger.info(
            f"[BrowserService.screenshot] Attempting to take screenshot to path: '{dest_str}'"
        )
        try:
            path_str = await self._session.screenshot(dest_str)
            logger.info(
                f"[BrowserService.screenshot] Screenshot successfully saved to '{path_str}'."
            )
        except Exception as e:
            logger.error(
                f"[BrowserService.screenshot] Failed to take screenshot to '{dest_str}': {e}",
                exc_info=True,
            )
            raise ScreenshotError(
                f"Failed to take screenshot to '{dest_str}': {e.__class__.__name__} - {e}"
            ) from e

        if dest is None:
            message = f"Screenshot saved to temporary file {path_str}. This file should be deleted after use."
        else:
            message = f"Screenshot saved to {path_str}"

        note = (
            "🔁 (browser had crashed – auto-restarted by initial _ensure_alive) "
            if restarted
            else ""
        )
        final_message = note + message
        logger.info(f"[BrowserService.screenshot] Completed. {final_message}")
        return path_str, final_message
