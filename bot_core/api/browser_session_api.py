"""
bot_core/api/browser_session_api.py
------------------
Generic browser session API for plugins and downstream consumers.
"""
import os
import time
import logging
from enum import Enum, auto
from typing import Optional
from bot_core.settings import settings

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
    def __init__(self, profile: Optional[str] = None):
        self.driver = None
        self.state = State.INITIAL
        self.profile = profile
        self._state_transition(State.SETUP)
        self.setup_driver()

    def _state_transition(self, new_state: State) -> None:
        previous_state = self.state
        self.state = new_state
        logger.info(f"[BrowserSession] State: {previous_state.name} -> {new_state.name}")

    def setup_driver(self) -> None:
        import undetected_chromedriver as uc
        chrome_options = uc.ChromeOptions()
        # Defensive fallback for download dir
        download_dir = str(settings.browser_download_dir or os.path.join(os.getcwd(), "browser_downloads"))
        prefs = {
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "download.default_directory": download_dir
        }
        chrome_options.add_experimental_option("prefs", prefs)
        profile_dir = self.profile or settings.chrome_profile_name or "Profile 1"
        user_data_dir = str(settings.chrome_profile_dir or os.path.expanduser("~/.config/google-chrome"))
        full_profile_path = os.path.join(user_data_dir, profile_dir)
        if os.path.exists(full_profile_path):
            chrome_options.add_argument(f"--user-data-dir={user_data_dir}")
            chrome_options.add_argument(f"--profile-directory={profile_dir}")
            logger.info(f"[BrowserSession] Using Chrome profile from '{full_profile_path}'.")
        else:
            logger.warning(f"[BrowserSession] Profile '{full_profile_path}' does not exist; using default profile.")
        driver_path = settings.chromedriver_path
        try:
            if driver_path:
                self.driver = uc.Chrome(driver_executable_path=driver_path, options=chrome_options)
            else:
                self.driver = uc.Chrome(options=chrome_options)
        except Exception as e:
            logger.error(f"[BrowserSession] Failed to launch Chrome: {e}")
            raise
        self._state_transition(State.IDLE)

    async def navigate(self, url: str) -> None:
        self._state_transition(State.NAVIGATING)
        import asyncio
        await asyncio.to_thread(self.driver.get, url)
        self._state_transition(State.IDLE)

    def screenshot(self, path: str) -> str:
        if not self.driver:
            raise RuntimeError("No browser session active.")
        # Ensure path is str for compatibility
        path_str = str(path)
        os.makedirs(os.path.dirname(os.path.abspath(path_str)) or str(settings.browser_download_dir), exist_ok=True)
        self.driver.save_screenshot(path_str)
        logger.info(f"[BrowserSession] Screenshot saved to {path_str}")
        return os.path.abspath(path_str)

    def download_asset(self, url: str, path: str) -> str:
        import requests
        path_str = str(path)
        os.makedirs(os.path.dirname(os.path.abspath(path_str)) or str(settings.browser_download_dir), exist_ok=True)
        try:
            resp = requests.get(url, stream=True)
            resp.raise_for_status()
            with open(path_str, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            logger.info(f"[BrowserSession] Asset downloaded to {path_str}")
            return os.path.abspath(path_str)
        except Exception as e:
            logger.error(f"[BrowserSession] Failed to download asset: {e}")
            raise

    def wait_for_duration(self, duration):
        self._state_transition(State.WAITING)
        logger.info(f"[BrowserSession] Waiting for {duration} seconds.")
        time.sleep(duration)
        self._state_transition(State.IDLE)

    def close(self) -> None:
        self._state_transition(State.CLOSING)
        if self.driver:
            try:
                self.driver.quit()
            except Exception as e:
                logger.info(f"[BrowserSession] Error quitting driver: {e}")
        self._state_transition(State.COMPLETED)

# Module-level session management
_session: Optional[BrowserSession] = None

# ---- compatibility layer (will be removed in v2) ---------------------
from bot_core.api.browser_service import default_browser_service as _svc

def start_browser_session(profile: str | None = None) -> str:
    # kept for one release cycle
    import asyncio
    return asyncio.run(_svc.start(profile=profile))   # noqa: S301

def stop_browser_session() -> str:
    return _svc.stop()

def get_browser_session_status() -> str:
    return _svc.status()
