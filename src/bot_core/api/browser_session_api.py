from pathlib import Path
import asyncio
import logging
from enum import Enum, auto
from typing import Optional, TYPE_CHECKING
from src.bot_core.settings import settings

"""
bot_core/api/browser_session_api.py
------------------
Browser session API for plugins and downstream consumers.

This module now only provides the BrowserSession class and its helpers. All legacy module-level session helpers have been removed.
"""

logger = logging.getLogger(__name__)


class State(Enum):
    INITIAL = auto()
    SETUP = auto()
    NAVIGATING = auto()
    WAITING = auto()
    IDLE = auto()
    CLOSING = auto()
    COMPLETED = auto()


class BrowserSession:
    def __init__(self, profile: Optional[str] = None, headless: bool | None = None):
        self.driver = None
        self.state = State.INITIAL
        self.profile = profile
        self._headless = headless
        self._state_transition(State.SETUP)
        self.setup_driver()

    def _state_transition(self, new_state: State) -> None:
        previous_state = self.state
        self.state = new_state
        logger.info(
            f"[BrowserSession] State: {previous_state.name} -> {new_state.name}"
        )

    def setup_driver(self) -> None:
        if TYPE_CHECKING:
            import undetected_chromedriver as uc
        else:
            import undetected_chromedriver as uc

            # Only patch Chrome.__del__ if it exists and we're not in a test environment
            try:
                if hasattr(uc.Chrome, "__del__"):
                    original_del = uc.Chrome.__del__

                    def safe_del(self):
                        try:
                            # Only call original if driver is still active
                            if (
                                hasattr(self, "service")
                                and self.service
                                and hasattr(self.service, "process")
                                and self.service.process
                            ):
                                original_del(self)
                        except Exception as e:
                            logger.info(
                                f"[BrowserSession] Suppressed error in Chrome.__del__: {e}"
                            )

                    # Apply the patch
                    uc.Chrome.__del__ = safe_del
                    logger.info(
                        "[BrowserSession] Applied Chrome.__del__ patch to prevent invalid handle errors"
                    )
            except Exception as e:
                logger.info(f"[BrowserSession] Could not patch Chrome.__del__: {e}")

        chrome_options = uc.ChromeOptions()
        # Defensive fallback for download dir
        download_dir = str(
            settings.browser_download_dir or (Path.cwd() / "browser_downloads")
        )
        prefs = {
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "download.default_directory": download_dir,
        }
        chrome_options.add_experimental_option("prefs", prefs)
        profile_dir = self.profile or settings.chrome_profile_name or "Profile 1"

        # Prioritize using the local ChromeProfiles directory in the project
        local_chrome_profiles = Path.cwd() / "ChromeProfiles"
        user_data_dir = str(settings.chrome_profile_dir or local_chrome_profiles)

        # Create the profile directory if it doesn't exist
        full_profile_path = Path(user_data_dir) / profile_dir
        if not full_profile_path.exists():
            try:
                full_profile_path.mkdir(parents=True, exist_ok=True)
                logger.info(
                    f"[BrowserSession] Created Chrome profile directory at '{full_profile_path}'"
                )
            except Exception as e:
                logger.warning(
                    f"[BrowserSession] Failed to create profile directory: {e}"
                )

        # Always use the profile directory - it now exists or we'll use it empty
        chrome_options.add_argument(f"--user-data-dir={user_data_dir}")
        chrome_options.add_argument(f"--profile-directory={profile_dir}")
        logger.info(f"[BrowserSession] Using Chrome profile from '{full_profile_path}'")
        # --------- browser flags ---------
        headless = (
            self._headless if self._headless is not None else settings.browser.headless
        )
        if headless:
            chrome_options.add_argument("--headless=new")
        if settings.browser.disable_gpu:
            chrome_options.add_argument("--disable-gpu")
        if settings.browser.no_sandbox:
            chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument(f"--window-size={settings.browser.window_size}")
        # --------- end browser flags -----
        driver_path = settings.chromedriver_path
        try:
            # Explicitly use Chrome version 136 to match the installed browser
            if driver_path:
                self.driver = uc.Chrome(
                    driver_executable_path=driver_path,
                    options=chrome_options,
                    version_main=136,
                )
            else:
                self.driver = uc.Chrome(options=chrome_options, version_main=136)
        except Exception as e:
            logger.error(f"[BrowserSession] Failed to launch Chrome: {e}")
            raise
        self._state_transition(State.IDLE)

    async def navigate(self, url: str) -> None:
        self._state_transition(State.NAVIGATING)
        import asyncio

        if self.driver is None:
            raise RuntimeError("No browser driver available.")

        # Ensure URL has proper protocol prefix
        if not url.startswith(("http://", "https://", "file://", "data:", "about:")):
            logger.info(f"[BrowserSession] Adding https:// prefix to URL: {url}")
            url = f"https://{url}"

        await asyncio.to_thread(self.driver.get, url)
        self._state_transition(State.IDLE)

    def screenshot(self, path: str) -> str:
        if not self.driver:
            raise RuntimeError("No browser session active.")
        # Ensure path is str for compatibility
        path_obj = Path(path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        self.driver.save_screenshot(str(path_obj))
        logger.info(f"[BrowserSession] Screenshot saved to {path_obj}")
        return str(path_obj.resolve())

    def download_asset(self, url: str, path: str) -> str:
        import requests  # type: ignore

        path_obj = Path(path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        try:
            resp = requests.get(url, stream=True)
            resp.raise_for_status()
            with path_obj.open("wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            logger.info(f"[BrowserSession] Asset downloaded to {path_obj}")
            return str(path_obj.resolve())
        except Exception as e:
            logger.error(f"[BrowserSession] Failed to download asset: {e}")
            raise

    async def wait_for_duration(self, duration: float) -> None:
        self._state_transition(State.WAITING)
        logger.info("Waiting for %s seconds", duration)
        await asyncio.sleep(duration)
        self._state_transition(State.IDLE)

    def get_current_url(self) -> str:
        """Get the current URL from the browser.

        Returns:
            The current URL as a string, or empty string if not available.
        """
        try:
            if self.driver and hasattr(self.driver, "current_url"):
                return self.driver.current_url
        except Exception as e:
            logger.info(f"[BrowserSession] Error getting current URL: {e}")
        return ""

    def close(self) -> None:
        self._state_transition(State.CLOSING)

        # Graceful driver shutdown to prevent invalid handle errors
        if self.driver:
            try:
                # First close all windows/tabs
                try:
                    if (
                        hasattr(self.driver, "window_handles")
                        and self.driver.window_handles
                    ):
                        for window in self.driver.window_handles[1:]:
                            self.driver.switch_to.window(window)
                            self.driver.close()
                        if self.driver.window_handles:
                            self.driver.switch_to.window(self.driver.window_handles[0])
                except Exception as e:
                    logger.info(f"[BrowserSession] Error closing windows: {e}")

                # Then quit the driver
                self.driver.quit()
                # Set to None to prevent further access attempts
                self.driver = None
            except Exception as e:
                logger.info(f"[BrowserSession] Error quitting driver: {e}")
                # Force cleanup to avoid garbage collection issues
                try:
                    self.driver = None
                except Exception:
                    pass

        self._state_transition(State.COMPLETED)
