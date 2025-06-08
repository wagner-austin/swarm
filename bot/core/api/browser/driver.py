"""Browser driver helpers: lazy-load undetected_chromedriver so the real
library (and its deprecation-prone helpers) are never imported during tests
unless explicitly requested.
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
import tempfile
from types import ModuleType
from typing import Optional, TYPE_CHECKING

from bot.core.settings import settings

if TYPE_CHECKING:
    import undetected_chromedriver as uc

logger = logging.getLogger(__name__)

# will hold the real or stubbed module *after* first use
_uc: ModuleType | None = None
_chrome_del_patched = False


def _get_uc() -> ModuleType:
    """Import undetected_chromedriver lazily so test stubs win."""
    global _uc
    if _uc is None:
        _uc = importlib.import_module("undetected_chromedriver")
    return _uc


def _patch_uc_chrome_del() -> None:
    """Patches undetected_chromedriver.Chrome.__del__ to suppress errors on exit."""
    global _chrome_del_patched
    if _chrome_del_patched:
        return

    uc = _get_uc()  # NEW
    try:
        if hasattr(uc.Chrome, "__del__"):
            original_del = uc.Chrome.__del__

            # Use a broad type here to avoid a
            # “Name 'uc.Chrome' is not defined” mypy error.  The
            # concrete type isn’t important for this runtime-only hook.
            def safe_del(self_chrome_instance: object) -> None:
                try:
                    if (
                        hasattr(self_chrome_instance, "service")
                        and self_chrome_instance.service
                        and hasattr(self_chrome_instance.service, "process")
                        and self_chrome_instance.service.process
                    ):
                        original_del(self_chrome_instance)
                except Exception as e:
                    logger.debug(
                        f"[BrowserDriver] Suppressed error in original Chrome.__del__: {e}"
                    )

            uc.Chrome.__del__ = safe_del
            _chrome_del_patched = True
            logger.info(
                "[BrowserDriver] Applied Chrome.__del__ patch to prevent invalid handle errors."
            )
    except Exception as e:
        logger.warning(f"[BrowserDriver] Could not patch Chrome.__del__: {e}")


def create_uc_driver(
    profile_name: Optional[str] = None,
    headless_mode: bool | None = None,
    version_main: int = 136,  # Default to a known working version
) -> "uc.Chrome":
    """Creates and configures an undetected_chromedriver instance."""
    uc = _get_uc()  # NEW
    _patch_uc_chrome_del()

    chrome_options = uc.ChromeOptions()

    if settings.proxy_enabled:
        proxy_port: int = settings.proxy_port or 9000
        # Use 127.0.0.1 instead of “localhost” to dodge IPv6 ↔ IPv4 mismatches.
        chrome_options.add_argument(f"--proxy-server=http://127.0.0.1:{proxy_port}")
        chrome_options.add_argument("--ignore-certificate-errors")
        logger.info(f"[BrowserDriver] Using proxy server http://127.0.0.1:{proxy_port}")
    else:
        logger.info("[BrowserDriver] Proxy not enabled or not configured in settings.")

    if settings.browser_download_dir:
        download_dir_path = Path(settings.browser_download_dir)
    else:
        # Use a dedicated folder in the system's temp directory
        download_dir_path = (
            Path(tempfile.gettempdir()) / "discord_bot_downloads" / "browser_default"
        )

    download_dir = str(download_dir_path.resolve())
    Path(download_dir).mkdir(parents=True, exist_ok=True)  # Ensure download dir exists

    prefs = {
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "download.default_directory": download_dir,
        "profile.default_content_setting_values.cookies": 1,  # Allow cookies
        "profile.block_third_party_cookies": False,  # Don't block third-party cookies
    }
    chrome_options.add_experimental_option("prefs", prefs)

    # Profile configuration
    actual_profile_name = (
        profile_name or settings.chrome_profile_name or "Default"
    )  # Changed from "Profile 1" to "Default"

    # Prefer local project directory for profiles
    default_user_data_dir_root = Path.cwd() / "ChromeProfiles"
    user_data_dir_root = settings.chrome_profile_dir or default_user_data_dir_root

    user_data_dir = Path(user_data_dir_root).resolve()

    # Ensure the root user data directory exists
    user_data_dir.mkdir(parents=True, exist_ok=True)
    # Profile specific directory will be created by Chrome if it doesn't exist, when using user-data-dir and profile-directory args

    chrome_options.add_argument(f"--user-data-dir={str(user_data_dir)}")
    chrome_options.add_argument(f"--profile-directory={actual_profile_name}")
    logger.info(f"[BrowserDriver] Using user data dir: {user_data_dir}")
    logger.info(f"[BrowserDriver] Using profile directory: {actual_profile_name}")

    # Headless mode
    # If headless_mode is explicitly passed, it takes precedence.
    # Otherwise, use settings.headless_mode (which defaults to True).
    is_headless = (
        headless_mode if headless_mode is not None else settings.browser.headless
    )
    logger.info(f"[BrowserDriver] Headless mode: {is_headless}")

    # Suppress welcome screen and default browser check
    chrome_options.add_argument("--no-first-run")
    chrome_options.add_argument("--no-default-browser-check")

    # Common options for stability / compatibility
    chrome_options.add_argument("--disable-infobars")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-popup-blocking")
    chrome_options.add_argument("--start-maximized")  # May help with element visibility
    # chrome_options.add_argument("--kiosk-printing") # If direct printing is ever needed

    try:
        logger.info(
            f"[BrowserDriver] Initializing Chrome driver version_main={version_main}, headless={is_headless}"
        )
        driver = uc.Chrome(
            options=chrome_options,
            headless=is_headless,
            version_main=version_main,
            user_data_dir=str(
                user_data_dir
            ),  # Pass explicitly here too, as per uc docs for consistency
        )
        logger.info("[BrowserDriver] Chrome driver initialized successfully.")
        return driver
    except Exception as e:
        logger.error(f"[BrowserDriver] Failed to launch Chrome: {e}", exc_info=True)
        # Attempt to provide more specific advice for common issues
        if "chrome_driver_executable" in str(e).lower():
            logger.error(
                "[BrowserDriver] Ensure ChromeDriver is installed and in your PATH, or specify its location."
            )
        elif "failed to get version_full" in str(e).lower():
            logger.error(
                "[BrowserDriver] uc failed to auto-detect Chrome version. Try specifying 'version_main' explicitly based on your installed Chrome."
            )
        raise
