# src/bot_core/api/browser/session.py
import asyncio
import logging
from enum import Enum, auto
from typing import Optional, cast, TYPE_CHECKING
from pathlib import Path
import requests  # For download_asset

from .driver import create_uc_driver

__all__ = [
    "BrowserSession",
    "State",
    "_normalise_url",
]  # Add _normalise_url to __all__ if it's to be used externally

if TYPE_CHECKING:
    import undetected_chromedriver as uc

logger = logging.getLogger(__name__)


def _normalise_url(url: str) -> str:
    """Ensure the URL has a scheme, defaulting to https if missing."""
    if not url.startswith(("http://", "https://", "file://", "data:", "about:")):
        logger.info(f"[BrowserSession] Adding https:// prefix to URL: {url}")
        return f"https://{url}"
    return url


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
        headless: bool | None = None,
        timeout: int = 60,
    ):
        self.driver: Optional[uc.Chrome] = None
        self.state = State.INITIAL
        self.profile_name = profile
        self.headless_mode = headless
        self.timeout = timeout

    async def initialize(self) -> None:
        self._state_transition(State.CREATING_DRIVER)
        try:
            # Create driver with timeout parameter
            logger.info(
                f"[BrowserSession] Starting Chrome initialization with timeout={self.timeout}s"
            )
            self.driver = await asyncio.to_thread(
                create_uc_driver,
                profile_name=self.profile_name,
                headless_mode=self.headless_mode,
                timeout=self.timeout,
            )
            logger.info("[BrowserSession] Chrome driver successfully initialized")
            self._state_transition(State.IDLE)
        except TimeoutError as e:
            logger.error(f"[BrowserSession] Timeout during driver initialization: {e}")
            self._state_transition(State.FAILED)
            raise RuntimeError(
                f"Browser initialization timed out after {self.timeout} seconds"
            ) from e
        except Exception as e:
            logger.error(
                f"[BrowserSession] Failed to initialize driver: {type(e).__name__}: {e}",
                exc_info=True,
            )
            self._state_transition(State.FAILED)
            # Add more context to the error to make debugging easier
            raise RuntimeError(
                f"Browser initialization failed: {type(e).__name__}: {e}"
            ) from e

    def _state_transition(self, new_state: State) -> None:
        previous_state = self.state
        self.state = new_state
        logger.info(
            f"[BrowserSession] State: {previous_state.name} -> {new_state.name}"
        )

    async def navigate(self, url: str) -> None:
        if self.state in [State.CLOSING, State.CLOSED, State.FAILED] or not self.driver:
            logger.warning(
                f"[BrowserSession] Cannot navigate in state {self.state.name} or no driver."
            )
            raise RuntimeError(
                f"Cannot navigate in state {self.state.name} or no driver."
            )

        self._state_transition(State.NAVIGATING)
        actual_url = _normalise_url(url)

        try:
            await asyncio.to_thread(self.driver.get, actual_url)
            self._state_transition(State.IDLE)
        except Exception:
            logger.exception("[BrowserSession] Navigation failed:")
            self._state_transition(State.FAILED)
            raise

    async def screenshot(self, path: str) -> str:
        if self.state in [State.CLOSING, State.CLOSED, State.FAILED] or not self.driver:
            logger.warning(
                f"[BrowserSession] Cannot take screenshot in state {self.state.name} or no driver."
            )
            raise RuntimeError(
                f"Cannot take screenshot in state {self.state.name} or no driver."
            )

        self._state_transition(State.SCREENSHOTTING)
        path_obj = Path(path)
        try:
            path_obj.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(self.driver.save_screenshot, str(path_obj))
            logger.info(f"[BrowserSession] Screenshot saved to {path_obj.resolve()}")
            self._state_transition(State.IDLE)
            return str(path_obj.resolve())
        except Exception as e:
            logger.error(f"[BrowserSession] Screenshot failed: {e}", exc_info=True)
            self._state_transition(State.FAILED)
            raise

    async def download_asset(self, url: str, path: str) -> str:
        if self.state in [State.CLOSING, State.CLOSED, State.FAILED]:
            logger.warning(
                f"[BrowserSession] Cannot download in state {self.state.name}."
            )
            raise RuntimeError(f"Cannot download in state {self.state.name}.")

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
            result_path = await asyncio.to_thread(_blocking_download)
            logger.info(f"[BrowserSession] Asset downloaded to {result_path}")
            self._state_transition(State.IDLE)
            return result_path
        except Exception as e:
            logger.error(
                f"[BrowserSession] Failed to download asset: {e}", exc_info=True
            )
            self._state_transition(State.FAILED)
            raise

    async def wait_for_duration(self, duration: float) -> None:
        if self.state in [State.CLOSING, State.CLOSED, State.FAILED]:
            logger.warning(f"[BrowserSession] Cannot wait in state {self.state.name}.")
            return  # Or raise error, depending on desired strictness

        self._state_transition(State.WAITING)
        logger.info(f"[BrowserSession] Waiting for {duration} seconds")
        await asyncio.sleep(duration)
        if (
            self.state == State.WAITING
        ):  # Ensure state hasn't changed (e.g. closed during wait)
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
            logger.debug(
                f"[BrowserSession] Cannot get URL in state {self.state.name} or no driver."
            )
            return ""
        try:
            return cast(str, self.driver.current_url)
        except Exception as e:
            logger.info(f"[BrowserSession] Error getting current URL: {e}")
            return ""

    async def close(self) -> None:
        if self.state == State.CLOSING or self.state == State.CLOSED:
            logger.info("[BrowserSession] Already closing or closed.")
            return

        self._state_transition(State.CLOSING)
        if self.driver:
            try:
                # Attempt graceful shutdown of tabs first if possible
                # This part is tricky with uc and can sometimes hang or error
                # For simplicity and robustness, directly calling quit() is often more reliable.
                # if hasattr(self.driver, 'window_handles') and self.driver.window_handles:
                #     for handle in self.driver.window_handles[1:]:
                #         self.driver.switch_to.window(handle)
                #         self.driver.close()
                #     if self.driver.window_handles: # Switch back to the first tab before quitting
                #         self.driver.switch_to.window(self.driver.window_handles[0])
                await asyncio.to_thread(self.driver.quit)
                logger.info("[BrowserSession] Driver quit successfully.")
            except Exception as e:
                logger.error(
                    f"[BrowserSession] Error during driver.quit(): {e}", exc_info=True
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
