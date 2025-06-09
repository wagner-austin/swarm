# src/bot_core/api/browser/session.py
import asyncio
import logging
from enum import Enum, auto
from typing import Optional, cast, TYPE_CHECKING
from pathlib import Path
from .exceptions import (
    BrowserInitializationError,
    BrowserStateError,
    NavigationError,
    ScreenshotError,  # Added to fix F821 Undefined name
)
import requests  # For download_asset

from .driver import create_uc_driver
from bot.utils.urls import normalise as _normalise_url  # Import from utils

__all__ = [
    "BrowserSession",
    "State",
    # "_normalise_url", # Removed as it's now imported
]

if TYPE_CHECKING:
    import undetected_chromedriver as uc

logger = logging.getLogger(__name__)

# _normalise_url is now imported from bot.utils.urls


class State(Enum):
    INITIAL = auto()  # Before driver setup
    CREATING_DRIVER = auto()  # Driver is being created
    IDLE = auto()  # Driver created, ready for commands
    NAVIGATING = auto()  # Actively navigating to a URL
    SCREENSHOTTING = auto()  # Taking a screenshot
    DOWNLOADING = auto()  # Downloading an asset
    WAITING = auto()  # Explicitly waiting (e.g., sleep)
    CLOSING = auto()  # Driver is being closed
    CLOSED = auto()  # Driver has been closed
    FAILED = auto()  # An unrecoverable error occurred


class BrowserSession:
    def __init__(
        self,
        profile: Optional[str] = None,
        headless: bool = True,  # Default to True, but BrowserService always provides it
        timeout: int = 60,
    ):
        self.driver: Optional[uc.Chrome] = None
        self.state = State.INITIAL
        self.profile_name = profile
        self.headless_mode = headless
        self.timeout = timeout
        logger.debug(
            f"[BrowserSession.__init__] Initialized with profile='{profile}', headless={headless}, timeout={timeout}s"
        )

    async def initialize(self) -> None:
        self._state_transition(State.CREATING_DRIVER)
        try:
            # Create driver with timeout parameter
            logger.debug(
                f"[BrowserSession.initialize] Starting Chrome initialization with profile='{self.profile_name}', headless={self.headless_mode}, timeout={self.timeout}s"
            )
            self.driver = await asyncio.to_thread(
                create_uc_driver,
                profile_name=self.profile_name,
                headless_mode=self.headless_mode,
                timeout=self.timeout,
            )
            logger.debug(
                "[BrowserSession.initialize] Chrome driver successfully initialized."
            )
            self._state_transition(State.IDLE)
        except TimeoutError as e:
            logger.error(
                f"[BrowserSession.initialize] Timeout during driver initialization after {self.timeout}s: {e}",
                exc_info=True,
            )  # Add exc_info for TimeoutError as well
            self._state_transition(State.FAILED)
            raise BrowserInitializationError(
                f"Browser initialization timed out after {self.timeout} seconds"
            ) from e
        except Exception as e:
            logger.error(
                f"[BrowserSession.initialize] Failed to initialize driver: {type(e).__name__}: {e}",
                exc_info=True,
            )
            self._state_transition(State.FAILED)
            # Add more context to the error to make debugging easier
            raise BrowserInitializationError(
                f"Browser initialization failed: {type(e).__name__}: {e}"
            ) from e

    def _state_transition(self, new_state: State) -> None:
        previous_state = self.state
        self.state = new_state
        logger.debug(
            f"[BrowserSession._state_transition] State: {previous_state.name} -> {new_state.name}"
        )

    async def navigate(self, url: str) -> None:
        if self.state in [State.CLOSING, State.CLOSED, State.FAILED] or not self.driver:
            logger.warning(
                f"[BrowserSession] Cannot navigate in state {self.state.name} or no driver."
            )
            raise BrowserStateError(
                f"Cannot navigate in state {self.state.name} or no driver."
            )

        logger.info(
            f"[BrowserSession.navigate] Attempting to navigate to URL: '{url}'. Normalized: '{_normalise_url(url)}'"
        )
        self._state_transition(State.NAVIGATING)
        actual_url = _normalise_url(url)

        try:
            await asyncio.to_thread(self.driver.get, actual_url)
            cur = getattr(self.driver, "current_url", "<unknown>")
            logger.info(
                f"[BrowserSession.navigate] Successfully navigated to '{actual_url}'. Current URL: '{cur}'"
            )
            self._state_transition(State.IDLE)
        except Exception as e:
            logger.error(
                f"[BrowserSession.navigate] Navigation to '{actual_url}' failed: {e}",
                exc_info=True,
            )
            self._state_transition(State.FAILED)
            raise NavigationError(
                f"Navigation to '{actual_url}' failed: {e.__class__.__name__} - {e}"
            ) from e

    async def screenshot(self, path: str) -> str:
        if self.state in [State.CLOSING, State.CLOSED, State.FAILED] or not self.driver:
            logger.warning(
                f"[BrowserSession] Cannot take screenshot in state {self.state.name} or no driver."
            )
            raise BrowserStateError(
                f"Cannot take screenshot in state {self.state.name} or no driver."
            )

        logger.info(
            f"[BrowserSession.screenshot] Attempting to save screenshot to path: '{path}'"
        )
        self._state_transition(State.SCREENSHOTTING)
        try:
            # Use a thread for the blocking screenshot operation
            success = await asyncio.to_thread(self.driver.save_screenshot, path)
            # Selenium returns bool, our stubs often return None
            if success is False:  # only explicit *False* is a failure
                logger.error(
                    f"[BrowserSession.screenshot] Screenshot to '{path}' failed (driver returned False)."
                )
                # self._state_transition(State.FAILED) # Or IDLE if it's not critical. Current ScreenshotError implies failure.
                raise ScreenshotError(
                    f"Screenshot to '{path}' failed (driver returned False)."
                )

            logger.info(
                f"[BrowserSession.screenshot] Screenshot successfully saved to '{path}'."
            )
            self._state_transition(State.IDLE)
            return path
        except Exception as e:
            logger.error(
                f"[BrowserSession.screenshot] Screenshot to '{path}' failed: {e}",
                exc_info=True,
            )
            self._state_transition(State.FAILED)
            raise

    async def download_asset(self, url: str, path: str) -> str:
        if self.state in [State.CLOSING, State.CLOSED, State.FAILED]:
            logger.warning(
                f"[BrowserSession] Cannot download in state {self.state.name}."
            )
            raise RuntimeError(f"Cannot download in state {self.state.name}.")

        logger.info(
            f"[BrowserSession.download_asset] Attempting to download from URL: '{url}' to path: '{path}'"
        )
        self._state_transition(State.DOWNLOADING)
        path_obj = Path(path)

        def _blocking_download() -> str:
            path_obj.parent.mkdir(parents=True, exist_ok=True)
            # Using requests for simplicity and robustness in downloading
            with requests.get(url, stream=True) as resp:
                resp.raise_for_status()
                with path_obj.open("wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)
            return str(path_obj.resolve())

        try:
            logger.debug(
                f"[BrowserSession.download_asset] Starting blocking download operation for '{url}' to '{path_obj}'."
            )
            result_path = await asyncio.to_thread(_blocking_download)
            logger.debug(
                f"[BrowserSession.download_asset] Blocking download operation for '{url}' to '{path_obj}' completed. Result path: '{result_path}'."
            )
            logger.info(
                f"[BrowserSession.download_asset] Asset successfully downloaded from '{url}' to '{result_path}'."
            )  # Kept as INFO for overall success
            # Original more verbose log, changed to debug as the one above is more concise for INFO level
            # logger.debug(f"[BrowserSession] Asset downloaded to {result_path}")
            self._state_transition(State.IDLE)
            return result_path
        except Exception as e:
            logger.error(
                f"[BrowserSession.download_asset] Failed to download asset from '{url}' to '{path}': {e}",
                exc_info=True,
            )
            self._state_transition(State.FAILED)
            raise

    async def wait_for_duration(self, duration: float) -> None:
        if self.state in [State.CLOSING, State.CLOSED, State.FAILED]:
            logger.warning(f"[BrowserSession] Cannot wait in state {self.state.name}.")
            return  # Or raise error, depending on desired strictness

        self._state_transition(State.WAITING)
        logger.debug(
            f"[BrowserSession.wait_for_duration] Waiting for {duration} seconds."
        )
        await asyncio.sleep(duration)
        if (
            self.state == State.WAITING
        ):  # Ensure state hasn't changed (e.g. closed during wait)
            logger.debug(
                "[BrowserSession.wait_for_duration] Wait completed. Transitioning to IDLE."
            )
            self._state_transition(State.IDLE)

    def is_alive(self) -> bool:
        """
        Try a *cheap* WebDriver call to prove the session is still valid.
        Any WebDriverException (invalid / closed session) → False.
        """
        if self.state in {State.CLOSED, State.CLOSING, State.FAILED} or not self.driver:
            return False
        from selenium.common.exceptions import WebDriverException

        # Test stubs mark themselves with “_dead”
        if getattr(self.driver, "_dead", False):
            return False

        # Some dummy drivers don’t implement .title — treat that as “still alive”
        try:
            _ = getattr(self.driver, "title", None)  # quick, never remote
            return True
        except (WebDriverException, AttributeError):
            return False

    def get_current_url(self) -> str:
        if self.state in [State.CLOSING, State.CLOSED, State.FAILED] or not self.driver:
            logger.warning(
                f"[BrowserSession.get_current_url] Cannot get URL in state {self.state.name} or no driver."
            )
            return ""
        try:
            return cast(str, self.driver.current_url)
        except Exception as e:
            logger.warning(
                f"[BrowserSession.get_current_url] Error getting current URL: {e}",
                exc_info=True,
            )
            return ""

    async def close(self) -> None:
        if self.state == State.CLOSING or self.state == State.CLOSED:
            logger.debug("[BrowserSession.close] Already closing or closed.")
            return

        self._state_transition(State.CLOSING)
        if self.driver:
            try:
                logger.debug("[BrowserSession.close] Attempting to quit driver.")
                await asyncio.to_thread(self.driver.quit)
                logger.debug("[BrowserSession.close] Driver quit successfully.")
            except Exception as e:
                logger.error(
                    f"[BrowserSession.close] Error during driver.quit(): {e}",
                    exc_info=True,
                )
            finally:
                self.driver = None  # Ensure driver is None after attempting to close

        self._state_transition(State.CLOSED)

    def __del__(self: "BrowserSession") -> None:
        # Ensure cleanup on garbage collection if close() wasn't explicitly called
        if self.driver is not None and self.state not in [State.CLOSING, State.CLOSED]:
            logger.warning(
                f"[BrowserSession] __del__ called on an active session (state: {self.state.name}). "
                f"The browser may not be properly closed. Ensure 'await session.close()' is called."
            )
            # Directly calling self.close() here is problematic as it's a coroutine.
            # For robust cleanup, users must explicitly call 'await session.close()'.
            # If we want to attempt a best-effort sync cleanup, it's complex and risky.
            # For now, we log a warning.
