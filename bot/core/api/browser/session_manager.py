# bot/core/api/browser/session_manager.py
"""Lifecycle (start/stop/restart/health) for a Chrome session.
No navigation logic – that lives in actions.py."""

from __future__ import annotations
import asyncio
import logging
from typing import Optional

from bot.core.settings import Settings, settings
from .session import BrowserSession
from .exceptions import (
    BrowserInitializationError,
    BrowserStateError,  # Used if start included navigation, kept for potential future use
)

logger = logging.getLogger(__name__)


class SessionManager:
    _restart_lock: asyncio.Lock = asyncio.Lock()

    def __init__(self, cfg: Settings = settings) -> None:
        self._settings: Settings = cfg
        self._session: Optional[BrowserSession] = None
        self._last_headless: bool = cfg.browser.headless
        self._last_url: Optional[str] = None
        self._session_ever_started: bool = False  # Track if a session was ever started

    def has_session(self) -> bool:
        """
        Return True if start() was called and we still have a BrowserSession
        object (even if it's now dead or manually closed/killed).
        Returns False if never started.
        """
        return self._session_ever_started

    async def start(
        self,
        # url: str | None = None, # Navigation removed from start, handled by BrowserActions
        *,
        headless: bool | None = None,
        profile: str | None = None,
        timeout: int = 60,
    ) -> str:
        logger.info(
            f"[SessionManager.start] Called with headless: {headless}, profile: {profile}, timeout: {timeout}"
        )
        if self._session and self._session.is_alive():
            logger.info("[SessionManager.start] Session already active and alive.")
            return "Browser session already started."

        # Mark that we've started a session
        self._session_ever_started = True

        effective_headless = (
            headless if headless is not None else self._settings.browser.headless
        )
        self._last_headless = effective_headless
        logger.debug(
            f"[SessionManager.start] Effective headless: {effective_headless}, stored _last_headless: {self._last_headless}"
        )

        if self._session:  # Ensure any old session is properly closed
            await self.stop()

        logger.info(
            f"[SessionManager.start] Initializing BrowserSession with profile='{profile}', headless={effective_headless}, timeout={timeout}s."
        )
        self._session = BrowserSession(
            profile=profile,
            headless=effective_headless,
            timeout=timeout,
        )
        try:
            logger.info("[SessionManager.start] Calling BrowserSession.initialize().")
            await self._session.initialize()
            logger.info("[SessionManager.start] BrowserSession.initialize() completed.")
            self._last_url = self._session.get_current_url()
            return f"Browser session started. Headless: {effective_headless}. Initial page: {self._last_url}"
        except BrowserInitializationError as e:
            logger.error(
                f"[SessionManager.start] BrowserSession.initialize() failed: {e}",
                exc_info=True,
            )
            self._session = None
            raise

    async def stop(self) -> str:
        logger.info("[SessionManager.stop] Called.")
        if not self._session:
            logger.info("[SessionManager.stop] No active session to stop.")
            # Note: we intentionally don't reset _session_ever_started here
            return "Browser session not active."

        # Capture the last URL before closing the session, but only if the session is still alive
        try:
            # First check if the session is alive before attempting to get the URL
            if self._session.is_alive():
                current_url = self._session.get_current_url()
                if (
                    current_url
                    and current_url != "about:blank"
                    and not current_url.startswith("chrome://")
                ):
                    logger.info(
                        f"[SessionManager.stop] Saving last URL before closing: {current_url}"
                    )
                    self._last_url = current_url
            else:
                logger.info(
                    "[SessionManager.stop] Session already dead, using existing _last_url"
                )
        except Exception as e:
            logger.warning(f"[SessionManager.stop] Failed to capture last URL: {e}")

        session_to_close = self._session
        self._session = None
        try:
            logger.info("[SessionManager.stop] Calling BrowserSession.close().")
            await session_to_close.close()
            logger.info("[SessionManager.stop] BrowserSession.close() completed.")
            # Important: DON'T clear self._last_url here so it can be restored later
            return "Browser session stopped."
        except Exception as e:
            logger.error(
                f"[SessionManager.stop] Error during BrowserSession.close(): {e}",
                exc_info=True,
            )
            return f"Browser session stopped, but an error occurred during cleanup: {e}"

    async def _ensure_alive(
        self,
        attempt_restart: bool = True,
        *,
        restore_last_url: bool = True,
    ) -> bool:
        logger.debug("[SessionManager._ensure_alive] Checking session status.")
        if self._session and self._session.is_alive():
            logger.debug("[SessionManager._ensure_alive] Session is active and alive.")
            return False

        if not attempt_restart:
            raise BrowserStateError("Browser session is not responding.")

        async with self._restart_lock:
            if self._session and self._session.is_alive():
                return False
            return await self._restart_session(restore_last_url=restore_last_url)

    async def _restart_session(self, *, restore_last_url: bool) -> bool:
        """Internal: create a fresh session and optionally restore last URL."""
        # Close dead session (if any)
        if self._session:
            try:
                await self._session.close()
            except Exception:
                pass

        self._session = BrowserSession(
            headless=self._last_headless,
            profile=None,  # Profile persistence is complex, start fresh for now
            timeout=60,  # TODO: Make configurable or use previous session's timeout
        )
        await self._session.initialize()  # This can raise BrowserInitializationError

        if restore_last_url and self._last_url:
            try:
                await self._session.navigate(self._last_url)
                # If navigation succeeds, get_current_url might differ (e.g. redirects)
                # but _last_url should reflect the *intended* target for restoration.
                # For simplicity, we don't re-assign self._last_url here from get_current_url()
                # as it was already set by the caller or previous successful navigation.
            except Exception as nav_exc:
                logger.warning(
                    f"[SessionManager._restart_session] Failed to restore URL '{self._last_url}': {nav_exc}"
                )
                # If restoration fails, _last_url is still the one we tried.
                # The session will be at its default page (e.g. about:blank).
        return True

    def status(self) -> str:
        logger.debug("[SessionManager.status] Generating status.")
        # Aligning with Memory 1b850db4
        if not self._session or not self._session.is_alive():
            mode = "headless" if self._settings.browser.headless else "visible"
            return f"Browser not running. Default mode: {mode}."

        # If session exists, check its state. BrowserSession.is_alive() is async.
        # For a sync status, we rely on available sync methods from BrowserSession.
        try:
            # Hypothetically, if BrowserSession cannot confirm it's alive synchronously and seems dead:
            # This part is tricky without an `is_alive_sync()` or if `is_alive()` is the only reliable check.
            # The original BrowserService.status was synchronous.
            # We'll assume if driver is running, we report based on session's current known state.
            # If BrowserSession.is_alive() was checked and it was false, _ensure_alive would have been called by actions.
            # This status method is a snapshot.

            # Based on Memory 1b850db4: "When no session is active or a session is dead,
            # the status now reflects the default mode configured in settings.py"
            # "If a session is live, it reports the mode that session is currently running in."

            # A practical approach for sync status: if self._session exists but we suspect it's dead
            # (e.g. last operation failed, or a quick sync check indicates non-responsiveness),
            # then report default. Otherwise, report live state.
            # For now, if self._session exists and driver is running, assume it's 'live' for status reporting purposes.
            # A truly 'dead' session should ideally be None after an op fails or _ensure_alive fails.

            current_url = self._session.get_current_url()  # Sync method
            mode = "headless" if self._session.headless_mode else "visible"

            status_msg = f"Browser running ({mode}). Current URL: {current_url or '(no URL loaded)'}"
            # Comparing with _last_url (last successfully set URL) might be confusing if current_url is just 'about:blank'
            # The original status didn't compare with _last_url in this way.
            return status_msg

        except Exception as e:
            logger.warning(
                f"[SessionManager.status] Error getting session details: {e}",
                exc_info=True,
            )
            mode = (
                "headless" if self._last_headless else "visible"
            )  # Fallback to intended mode
            return f"Browser session state uncertain. Intended mode: {mode}. Error: {e}"

    async def get_alive_session(self) -> BrowserSession:
        logger.debug("[SessionManager.get_alive_session] Ensuring session is alive.")
        await self._ensure_alive()

        if not self._session:
            logger.error(
                "[SessionManager.get_alive_session] Session is None after _ensure_alive."
            )
            raise BrowserStateError(
                "Browser session not available after attempting to ensure it's alive."
            )

        if not self._session.is_alive():  # Final check
            logger.error(
                "[SessionManager.get_alive_session] Session not alive after _ensure_alive attempt."
            )
            # _ensure_alive should raise if it fails to make it alive. This is a safeguard.
            self._session = None  # Mark session as unusable
            raise BrowserStateError(
                "Browser session is not responding after attempting to ensure it's alive."
            )

        return self._session

    # Method for BrowserActions to update last known URL after successful navigation
    def _update_last_url(self, url: str | None) -> None:
        self._last_url = url

    # Public method that delegates to _update_last_url
    def remember_url(self, url: str | None) -> None:
        """Remember the last URL a session was on. Public API for BrowserActions."""
        self._update_last_url(url)

    async def shutdown(self) -> None:
        """Gracefully shuts down the browser session. Alias for stop()."""
        logger.info("[SessionManager.shutdown] Called, delegating to stop().")
        await self.stop()


# public re-export
__all__ = ["SessionManager"]
