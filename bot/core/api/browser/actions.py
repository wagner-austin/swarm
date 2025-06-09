# bot/core/api/browser/actions.py
"""Side-effects executed *inside* a live session: open URL, screenshot, download."""

from __future__ import annotations
import logging
import tempfile
import os
from pathlib import Path
from bot.utils.urls import validate_and_normalise_web_url
from .exceptions import InvalidURLError, NavigationError, ScreenshotError
from .session_manager import SessionManager

logger = logging.getLogger(__name__)


class BrowserActions:
    def __init__(self, mgr: SessionManager) -> None:
        self._mgr = mgr

    async def open(self, url: str) -> str:
        logger.info(f"[BrowserActions.open] Called with URL: {url}")
        if not url:
            raise InvalidURLError("URL cannot be empty.")

        try:
            actual_url = validate_and_normalise_web_url(url)
        except ValueError as ve:
            raise InvalidURLError(str(ve)) from ve

        logger.debug("[BrowserActions.open] Normalised & validated URL: %s", actual_url)

        # get (or revive) a live browser session
        session = await self._mgr.get_alive_session()

        try:
            logger.info(
                f"[BrowserActions.open] Navigating to {actual_url} using session."
            )
            current_url_after_nav = await self._navigate(session, actual_url)
            logger.info(
                "[BrowserActions.open] Navigation complete → %s", current_url_after_nav
            )
            return f"Navigation complete: {current_url_after_nav}"
        except NavigationError as first_err:
            logger.warning(
                "[BrowserActions.open] Navigation failed – trying automatic session revive: %s",
                first_err,
            )
            try:
                # Bring the session back, but do NOT auto‑navigate – we will
                # do the navigation ourselves right afterwards.
                await self._mgr._ensure_alive(restore_last_url=False)
                session = await self._mgr.get_alive_session()
                current_url_after_nav = await self._navigate(session, actual_url)
                logger.info(
                    f"[BrowserActions.open] Navigation succeeded after auto-revive → {current_url_after_nav}"
                )
                return f"Navigation complete: {current_url_after_nav}"
            except (
                Exception
            ) as retry_err:  # Catch any error during retry (NavigationError or other)
                logger.error(
                    f"[BrowserActions.open] Auto-revive attempt failed for URL '{actual_url}' after initial error '{first_err}': {retry_err}",
                    exc_info=True,  # Log the retry_err
                )
                # Try to update last_url with the current URL of the session used in the retry attempt
                try:
                    url_after_failed_retry = session.get_current_url()
                    self._mgr.remember_url(url_after_failed_retry)
                except Exception:
                    self._mgr.remember_url(None)
                raise first_err  # still broken ➜ bubble original error up (first_err)
        except Exception as e:
            logger.error(
                f"[BrowserActions.open] Unexpected error during navigation to '{actual_url}': {e}",
                exc_info=True,
            )
            try:
                self._mgr.remember_url(session.get_current_url())
            except Exception:
                self._mgr.remember_url(None)
            raise NavigationError(
                f"Unexpected error navigating to '{actual_url}': {e}"
            ) from e

    async def screenshot(self, dest: str | None = None) -> tuple[str, str]:
        logger.info(
            f"[BrowserActions.screenshot] Called with destination: '{dest if dest else 'temporary file'}'"
        )
        session = await self._mgr.get_alive_session()

        is_temp_file = False
        if dest is None:
            logger.debug(
                "[BrowserActions.screenshot] No destination path provided, creating temporary file path."
            )
            # Get a temporary file path. session.screenshot will handle file creation.
            fd, dest_str = tempfile.mkstemp(suffix=".png")
            os.close(fd)  # Close the file descriptor immediately
            is_temp_file = True
        else:
            dest_str = dest

        logger.info(
            f"[BrowserActions.screenshot] Attempting to take screenshot to path: '{dest_str}' using session."
        )
        try:
            path_str = await session.screenshot(dest_str)
            logger.info(
                f"[BrowserActions.screenshot] Screenshot successfully saved to '{path_str}'."
            )
        except Exception as e:
            logger.error(
                f"[BrowserActions.screenshot] Failed to take screenshot to '{dest_str}': {e}",
                exc_info=True,
            )
            if is_temp_file:
                try:
                    Path(dest_str).unlink(missing_ok=True)
                    logger.info(
                        f"[BrowserActions.screenshot] Cleaned up temporary file '{dest_str}' after error."
                    )
                except Exception as cleanup_e:
                    logger.error(
                        f"[BrowserActions.screenshot] Error cleaning up temp file '{dest_str}': {cleanup_e}"
                    )
            raise ScreenshotError(
                f"Failed to take screenshot to '{dest_str}': {e}"
            ) from e

        message = f"Screenshot saved to {path_str}"
        # If dest was None, path_str is a temporary file. The cog (caller) is responsible for deleting it after use
        # if session.screenshot was successful. The cleanup above handles errors during session.screenshot itself.

        logger.info(f"[BrowserActions.screenshot] Completed. {message}")
        return path_str, message

    async def download(self, url: str, dest_file_path: Path) -> str:
        """Navigates to a URL to trigger a download, then attempts to find and move the downloaded file."""
        logger.info(
            f"[BrowserActions.download] Called with URL: {url}, target file path: {dest_file_path}"
        )
        session = await self._mgr.get_alive_session()

        # Ensure destination directory exists
        dest_file_path.parent.mkdir(parents=True, exist_ok=True)

        # This is a simplified conceptual implementation.
        # Robustly handling downloads (especially knowing the filename and completion) is complex.
        # It often requires checking the download directory for new files, handling temp names, etc.
        # BrowserSession would need more sophisticated download tracking capabilities.

        # For now, assume BrowserSession.download(url, target_path) exists and handles it.
        # If not, this needs more detailed implementation using navigation + file system watching.
        if hasattr(
            session, "download_file_and_move"
        ):  # Check for a hypothetical advanced download method
            try:
                actual_download_path = await session.download_file_and_move(
                    url, dest_file_path
                )
                msg = f"Download initiated for {url}. File saved to {actual_download_path}."
                logger.info(msg)
                return msg
            except Exception as e:
                logger.error(
                    f"[BrowserActions.download] Error during download_file_and_move: {e}",
                    exc_info=True,
                )
                raise NavigationError(
                    f"Failed to download from '{url}' to '{dest_file_path}': {e}"
                ) from e
        else:
            # Fallback: Navigate and hope for the best (very basic)
            logger.warning(
                "[BrowserActions.download] Using basic navigation for download. Robust download tracking not implemented."
            )
            await self.open(url)  # Navigate to the URL
            # User must manually check session.download_dir for the file.
            # This doesn't use dest_file_path effectively without more logic.
            msg = (
                f"Navigation to {url} initiated. "
                "Check the browser's configured download directory and move the file manually."
            )
            logger.info(msg)
            return msg

    # ------------------------------------------------------------------+
    #  Shared navigation helper                                         +
    # ------------------------------------------------------------------+

    from typing import TYPE_CHECKING

    if TYPE_CHECKING:  # avoid import cycle at runtime
        from .session import BrowserSession

    async def _navigate(self, session: "BrowserSession", url: str) -> str:
        """Navigate, remember URL, return the resulting location."""
        await session.navigate(url)
        cur: str = session.get_current_url()
        self._mgr.remember_url(cur)
        return cur


__all__ = ["BrowserActions"]
