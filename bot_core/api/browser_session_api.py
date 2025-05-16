from pathlib import Path
import asyncio
import logging
from enum import Enum, auto
from typing import Optional, TYPE_CHECKING
from bot_core.settings import settings

"""
bot_core/api/browser_session_api.py
------------------
Generic browser session API for plugins and downstream consumers.
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
        user_data_dir = str(
            settings.chrome_profile_dir or (Path.home() / ".config" / "google-chrome")
        )
        full_profile_path = Path(user_data_dir) / profile_dir
        if full_profile_path.exists():
            chrome_options.add_argument(f"--user-data-dir={user_data_dir}")
            chrome_options.add_argument(f"--profile-directory={profile_dir}")
            logger.info(
                f"[BrowserSession] Using Chrome profile from '{full_profile_path}'."
            )
        else:
            logger.warning(
                f"[BrowserSession] Profile '{full_profile_path}' does not exist; using default profile."
            )
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
            if driver_path:
                self.driver = uc.Chrome(
                    driver_executable_path=driver_path, options=chrome_options
                )
            else:
                self.driver = uc.Chrome(options=chrome_options)
        except Exception as e:
            logger.error(f"[BrowserSession] Failed to launch Chrome: {e}")
            raise
        self._state_transition(State.IDLE)

    async def navigate(self, url: str) -> None:
        self._state_transition(State.NAVIGATING)
        import asyncio

        if self.driver is None:
            raise RuntimeError("No browser driver available.")
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

    def close(self) -> None:
        self._state_transition(State.CLOSING)
        if self.driver:
            try:
                self.driver.quit()
            except Exception as e:
                logger.info(f"[BrowserSession] Error quitting driver: {e}")
        self._state_transition(State.COMPLETED)


# Module-level session management (legacy helpers – scheduled for removal)
_session: Optional[BrowserSession] = None

# ---- backwards-compat wrappers ----------------------------------------

if TYPE_CHECKING:
    from bot_core.api.browser_service import BrowserService


def _default_service() -> "BrowserService":
    """Late import to avoid circular dependency with browser_service.py."""
    from bot_core.api.browser_service import default_browser_service

    return default_browser_service


def start_browser_session(profile: str | None = None) -> str:
    import asyncio

    return asyncio.run(_default_service().start(profile=profile))


def stop_browser_session() -> str:
    import asyncio

    return asyncio.run(_default_service().stop())


def get_browser_session_status() -> str:
    return _default_service().status()
