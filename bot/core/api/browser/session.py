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
    def __init__(self, profile: Optional[str] = None, headless: bool | None = None):
        self.driver: Optional[uc.Chrome] = None
        self.state = State.INITIAL
        self.profile_name = profile
        self.headless_mode = headless
        self._initialize_driver()

    def _initialize_driver(self) -> None:
        self._state_transition(State.CREATING_DRIVER)
        try:
            self.driver = create_uc_driver(
                profile_name=self.profile_name, headless_mode=self.headless_mode
            )
            self._state_transition(State.IDLE)
        except Exception as e:
            logger.error(
                f"[BrowserSession] Failed to initialize driver: {e}", exc_info=True
            )
            self._state_transition(State.FAILED)
            # self.driver will remain None

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
        except Exception as e:
            logger.error(f"[BrowserSession] Navigation failed: {e}", exc_info=True)
            self._state_transition(State.FAILED)
            raise

    def screenshot(self, path: str) -> str:
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
            self.driver.save_screenshot(str(path_obj))
            logger.info(f"[BrowserSession] Screenshot saved to {path_obj.resolve()}")
            self._state_transition(State.IDLE)
            return str(path_obj.resolve())
        except Exception as e:
            logger.error(f"[BrowserSession] Screenshot failed: {e}", exc_info=True)
            self._state_transition(State.FAILED)
            raise

    def download_asset(self, url: str, path: str) -> str:
        if self.state in [State.CLOSING, State.CLOSED, State.FAILED]:
            logger.warning(
                f"[BrowserSession] Cannot download in state {self.state.name}."
            )
            raise RuntimeError(f"Cannot download in state {self.state.name}.")

        self._state_transition(State.DOWNLOADING)
        path_obj = Path(path)
        try:
            path_obj.parent.mkdir(parents=True, exist_ok=True)
            # Using requests for simplicity and robustness in downloading
            with requests.get(url, stream=True) as resp:
                resp.raise_for_status()
                with path_obj.open("wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)
            logger.info(f"[BrowserSession] Asset downloaded to {path_obj.resolve()}")
            self._state_transition(State.IDLE)
            return str(path_obj.resolve())
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

    def close(self) -> None:
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
                self.driver.quit()
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
        if self.state not in [State.CLOSING, State.CLOSED]:
            logger.info(
                f"[BrowserSession] __del__ called in state {self.state.name}. Attempting cleanup."
            )
            self.close()
