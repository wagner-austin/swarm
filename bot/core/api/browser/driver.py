"""Browser driver helpers: lazy-load undetected_chromedriver so the real
library (and its deprecation-prone helpers) are never imported during tests
unless explicitly requested.
"""

from __future__ import annotations

import importlib
import logging
from selenium.common.exceptions import SessionNotCreatedException
import shutil
import pathlib
import tempfile
from pathlib import Path
from types import ModuleType  # ✔ real home of ModuleType
from typing import TYPE_CHECKING, Any

from bot.core.settings import settings

# lazy-load helper already handles the real import
if TYPE_CHECKING:
    import undetected_chromedriver as uc

import socket


def _proxy_alive(host: str = "127.0.0.1", port: int = 9000) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.3):
            return True
    except OSError:
        return False


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

    uc = _get_uc()
    try:
        if hasattr(uc.Chrome, "__del__"):
            original_del = uc.Chrome.__del__

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
    profile_name: str | None = None,
    headless_mode: bool | None = None,
    version_main: int | None = settings.browser_version_main,
    proxy_config: dict[str, Any] | None = None,
    user_data_dir_base: str | None = None,
    timeout: int = 60,  # Add timeout parameter
) -> "uc.Chrome":
    """Creates and configures an undetected_chromedriver instance."""
    uc = _get_uc()
    _patch_uc_chrome_del()

    chrome_options = uc.ChromeOptions()

    # Add flags to prevent "restore pages" popup and other notification bars
    chrome_options.add_argument("--no-first-run")
    chrome_options.add_argument("--disable-infobars")
    chrome_options.add_argument("--disable-session-crashed-bubble")
    chrome_options.add_argument("--hide-crash-restore-bubble")   # Chrome ≥115

    _actual_proxy_port_for_check = settings.proxy_port or 9000
    if settings.proxy_enabled and _proxy_alive(
        "127.0.0.1", _actual_proxy_port_for_check
    ):
        proxy_argument_port = settings.proxy_port or 9000
        chrome_options.add_argument(
            f"--proxy-server=http://127.0.0.1:{proxy_argument_port}"
        )
        chrome_options.add_argument("--ignore-certificate-errors")
        # Prevent DevTools port loop-back dead-lock
        chrome_options.add_argument(
            "--proxy-bypass-list=<-loopback>;localhost;127.0.0.1"
        )
        logger.info(
            f"[BrowserDriver] Using proxy server http://127.0.0.1:{proxy_argument_port}"
        )
    else:
        logger.info("[BrowserDriver] Proxy not running - launching Chrome without it.")

    if settings.browser_download_dir is not None:
        download_dir_path = Path(settings.browser_download_dir)
    else:
        download_dir_path = (
            Path(tempfile.gettempdir()) / "discord_bot_downloads" / "browser_default"
        )

    download_dir = str(download_dir_path.resolve())
    Path(download_dir).mkdir(parents=True, exist_ok=True)

    prefs = {
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "download.default_directory": download_dir,
        "profile.default_content_setting_values.cookies": 1,
        "profile.block_third_party_cookies": False,
    }
    chrome_options.add_experimental_option("prefs", prefs)

    actual_profile_name = profile_name or settings.chrome_profile_name or "Default"

    default_user_data_dir_root = Path.cwd() / "ChromeProfiles"
    user_data_dir_root = settings.chrome_profile_dir or default_user_data_dir_root

    user_data_dir = Path(user_data_dir_root).resolve()

    user_data_dir.mkdir(parents=True, exist_ok=True)
    chrome_options.add_argument(f"--user-data-dir={str(user_data_dir)}")
    chrome_options.add_argument(f"--profile-directory={actual_profile_name}")
    logger.info(f"[BrowserDriver] Using user data dir: {user_data_dir}")
    logger.info(f"[BrowserDriver] Using profile directory: {actual_profile_name}")

    chrome_options.add_argument("--no-first-run")
    chrome_options.add_argument("--no-default-browser-check")

    chrome_options.add_argument("--disable-infobars")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-popup-blocking")
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--log-level=3")

    try:
        # Log more details about the initialization attempt for debugging
        logger.info(
            f"[BrowserDriver] Initializing Chrome with settings:\n"
            f"  - Headless mode: {headless_mode}\n"
            f"  - Version main: {version_main}\n"
            f"  - User data dir: {user_data_dir}\n"
            f"  - Profile: {actual_profile_name}"
        )

        import concurrent.futures
        import time

        # Use a thread executor with timeout to avoid hanging indefinitely
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            try:
                # Start timer for performance tracking
                start_time = time.time()
                logger.debug(
                    f"[BrowserDriver] Attempting uc.Chrome driver creation with timeout={timeout}s"
                )

                # Submit the driver creation task to the executor
                future = executor.submit(
                    lambda: uc.Chrome(
                        options=chrome_options,
                        headless=headless_mode,
                        version_main=None,  # Use None to allow auto-detection
                        user_data_dir=str(user_data_dir),
                        use_subprocess=True,  # Use subprocess for better isolation
                    )
                )

                # Wait for the driver with a timeout
                driver = future.result(timeout=timeout)

                elapsed = time.time() - start_time
                logger.info(
                    f"[BrowserDriver] Chrome driver initialized successfully in {elapsed:.2f}s"
                )
                return driver

            except concurrent.futures.TimeoutError:
                logger.error(
                    f"[BrowserDriver] Chrome driver initialization timed out after {timeout}s"
                )
                raise RuntimeError(
                    f"Chrome driver initialization timed out after {timeout} seconds. "
                    "This might be due to Chrome hanging during startup."
                ) from None

            except TypeError as e:
                logger.warning(
                    f"[BrowserDriver] TypeError during uc.Chrome initialization: {e}. "
                    "Attempting with minimal options."
                )

                # Try again with minimal options
                future = executor.submit(
                    lambda: uc.Chrome(
                        options=chrome_options,
                        headless=headless_mode,
                        version_main=None,
                    )
                )

                driver = future.result(timeout=timeout)
                logger.info(
                    "[BrowserDriver] Chrome driver initialized successfully with minimal options"
                )
                return driver
    except SessionNotCreatedException as e:
        if version_main is None:
            logger.error(
                "[BrowserDriver] SessionNotCreatedException even after auto-detect retry: %s",
                e,
                exc_info=True,
            )
            raise

        logger.warning(
            f"[BrowserDriver] SessionNotCreatedException with version_main='{version_main}': {e}. "
            f"Assuming driver/browser version mismatch. Clearing cache and retrying with auto-detect."
        )
        module_file_path = uc.__file__
        if module_file_path is None:
            logger.error(
                "[BrowserDriver] uc module's __file__ attribute is None. Cannot determine cache path. "
                "Skipping cache clear and re-raising original error. This is unexpected if the "
                "SessionNotCreatedException originated from the real undetected_chromedriver."
            )
            raise  # Re-raise the original SessionNotCreatedException

        # module_file_path is now confirmed to be a str
        uc_driver_cache_dir = pathlib.Path(module_file_path).resolve().parent / "driver"

        if uc_driver_cache_dir.is_dir():
            logger.info(
                f"[BrowserDriver] Attempting to remove uc cache directory: {uc_driver_cache_dir}"
            )
            shutil.rmtree(uc_driver_cache_dir, ignore_errors=True)
            logger.info(
                f"[BrowserDriver] Removed uc cache directory (or operation ignored errors): {uc_driver_cache_dir}"
            )
        else:
            logger.warning(
                f"[BrowserDriver] uc cache path {uc_driver_cache_dir} not found or not a directory. Skipping cache clear."
            )

        logger.info(
            "[BrowserDriver] Retrying create_uc_driver with version_main=None (auto-detect)."
        )
        return create_uc_driver(
            profile_name=profile_name,
            headless_mode=headless_mode,
            version_main=None,
            proxy_config=proxy_config,
            user_data_dir_base=user_data_dir_base,
        )
    except Exception as e:
        logger.error(
            "[BrowserDriver] Failed to launch Chrome (outer exception): %s",
            e,
            exc_info=True,
        )
        raise
