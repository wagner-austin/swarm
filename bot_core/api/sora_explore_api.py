#!/usr/bin/env python3
"""
core/api/sora_explore_api.py --- Sora Explore API for managing sessions with improved video handling.
"""
import os
import time
import logging
import requests
from enum import Enum, auto
from urllib.parse import urlparse, unquote

import undetected_chromedriver as uc
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By

logger = logging.getLogger(__name__)

# -----------------------------
# Configuration
# -----------------------------
BASE_URL = "https://www.sora.com/explore"
KEEP_BROWSER_OPEN = True
BROWSER_STAY_DURATION = 5  # Seconds to keep the browser open
USE_EXISTING_PROFILE = True

# -----------------------------
# State Definition
# -----------------------------
class State(Enum):
    INITIAL = auto()
    SETUP = auto()
    NAVIGATING = auto()
    CAPTURING = auto()
    DOWNLOADING = auto()
    WAITING = auto()
    IDLE = auto()
    CLOSING = auto()
    COMPLETED = auto()

# -----------------------------
# Plugin Manager for Sora
# -----------------------------
class PluginManagerForSora:
    """
    Manages internal plugins and dispatches state change events.
    """
    def __init__(self):
        self.plugins = []

    def register_plugin(self, plugin):
        self.plugins.append(plugin)
        logger.info(f"(Sora) Plugin {plugin.__class__.__name__} registered.")

    def notify_state_change(self, previous_state, new_state, opener):
        for plugin in self.plugins:
            try:
                plugin.on_state_change(previous_state, new_state, opener)
            except Exception as e:
                logger.error(f"(Sora) Error in plugin {plugin.__class__.__name__}: {e}")

class LoggingPlugin:
    def on_state_change(self, previous_state, new_state, opener):
        logger.info(f"(Sora) State changed from {previous_state.name} to {new_state.name}.")

# -----------------------------
# SimpleOpener Implementation
# -----------------------------
class SimpleOpener:
    """
    Opens Chrome using undetected_chromedriver, navigates to the Sora Explore page,
    and manages state transitions. The download/capture operation is triggered separately
    via capture_detailed_info().
    """
    def __init__(self, driver_path=None, plugin_manager=None, settings: Settings = None):
        self.driver = None
        self.wait = None
        self.driver_path = driver_path
        self.state = State.INITIAL
        self.plugin_manager = plugin_manager
        self.settings = settings or _default_settings
        self._state_transition(State.SETUP)
        self.setup_driver()

    def _state_transition(self, new_state):
        previous_state = self.state
        self.state = new_state
        if self.plugin_manager:
            self.plugin_manager.notify_state_change(previous_state, new_state, self)

    def setup_driver(self):
        chrome_options = uc.ChromeOptions()
        prefs = {
            "download.prompt_for_download": False,
            "download.directory_upgrade": True
        }
        chrome_options.add_experimental_option("prefs", prefs)

        if USE_EXISTING_PROFILE:
            user_data_dir = getattr(self.settings, "user_data_dir", r"C:\Users\Test\PROJECTS\sora\ChromeProfiles")
            profile_directory = getattr(self.settings, "profile_directory", "Profile 1")
            full_profile_path = os.path.join(user_data_dir, profile_directory)
            if os.path.exists(full_profile_path):
                chrome_options.add_argument(f"--user-data-dir={full_profile_path}")
                logger.info(f"(Sora) Using dedicated profile from '{full_profile_path}'.")
            else:
                logger.warning(f"(Sora) Profile '{full_profile_path}' does not exist; launching default profile.")
        else:
            logger.info("(Sora) Not using an existing profile. Launching with default profile.")

        if self.driver_path:
            self.driver = uc.Chrome(driver_executable_path=self.driver_path, options=chrome_options)
        else:
            self.driver = uc.Chrome(options=chrome_options)
        self.wait = WebDriverWait(self.driver, 20)

    def open_url(self):
        self._state_transition(State.NAVIGATING)
        logger.info(f"(Sora) Attempting to navigate to {BASE_URL}")
        self.driver.get(BASE_URL)
        time.sleep(2)  # Allow time for navigation to complete

        current_url = self.driver.current_url
        if "sora.com/explore" in current_url:
            logger.info(f"(Sora) Navigation successful. Current URL: {current_url}")
        else:
            logger.warning(f"(Sora) Navigation may have failed. Current URL: {current_url}")

        # Move to IDLE state after successfully opening the page
        self._state_transition(State.IDLE)

    def _get_media_element(self):
        """
        Helper method to locate and return the media element along with its type.
        
        Returns:
            tuple: (media_element, media_type) where media_type is 'image' or 'video'
            
        Raises:
            Exception: If no media element is found.
        """
        try:
            media_element = self.wait.until(
                lambda d: d.find_element(By.CSS_SELECTOR, "img[alt='Generated image']")
            )
            return media_element, "image"
        except Exception:
            pass  # Continue to try locating a video element

        try:
            # Attempt to locate a video element
            media_element = self.wait.until(lambda d: d.find_element(By.CSS_SELECTOR, "video"))
            # Try getting the src attribute; if not available, look for a child <source>
            media_url = media_element.get_attribute("src")
            if not media_url:
                try:
                    source = media_element.find_element(By.TAG_NAME, "source")
                    media_url = source.get_attribute("src")
                except Exception:
                    pass
            return media_element, "video"
        except Exception as e:
            raise Exception(f"(Sora) Media element not found: {e}")

    def capture_detailed_info(self) -> dict:
        """
        Captures and downloads info from the first thumbnail link on the page,
        including proper video handling, then returns to the previous page.
        Transitions the session through CAPTURING -> DOWNLOADING -> IDLE states.
        
        Returns:
            A dictionary containing:
              - file_path: The full path to the saved media file.
              - media_type: Either 'image' or 'video'.
              - detailed_info: Additional captured details.
        """
        self._state_transition(State.CAPTURING)
        try:
            thumbnail = self.wait.until(lambda d: d.find_element(By.CSS_SELECTOR, "a[href^='/g/']"))
        except Exception as e:
            logger.warning(f"(Sora) Detailed page link not found: {e}")
            self._state_transition(State.IDLE)
            return {}
        
        detailed_path = thumbnail.get_attribute("href")
        detailed_url = "https://sora.com" + detailed_path if detailed_path.startswith("/") else detailed_path

        # Capture artist info if available
        artist = ""
        try:
            container = thumbnail.find_element(By.XPATH, "..")
            artist_element = container.find_element(By.CSS_SELECTOR, "button span.truncate")
            artist = artist_element.text.strip()
        except Exception as e:
            logger.warning(f"(Sora) Artist not found: {e}")

        logger.info(f"(Sora) Navigating to detailed page: {detailed_url}")
        self.driver.get(detailed_url)

        try:
            # Use the helper method to get the media element and its type.
            media_element, media_type = self._get_media_element()

            # Retrieve media URL with a fallback for video elements
            media_url = media_element.get_attribute("src")
            if media_type == "video" and not media_url:
                try:
                    source = media_element.find_element(By.TAG_NAME, "source")
                    media_url = source.get_attribute("src")
                except Exception as e:
                    raise Exception(f"(Sora) Video source not available: {e}")

            # Transition to downloading state
            self._state_transition(State.DOWNLOADING)
            logger.info(f"(Sora) Detailed page {media_type} URL: {media_url}")

            parsed_url = urlparse(media_url)
            decoded_path = unquote(parsed_url.path)
            prefix = "/vg-assets/"
            if decoded_path.startswith(prefix):
                decoded_path = decoded_path[len(prefix):]
            name_without_ext, ext = os.path.splitext(decoded_path)

            # Force correct file extension: override any existing extension if media is video.
            if media_type == "video":
                ext = ".mp4"
            elif not ext:
                ext = ".webp"
            final_filename = name_without_ext.replace("/", "_") + ext

            try:
                file_path = self._save_media(media_url, final_filename)
            except Exception as e:
                logger.warning(f"(Sora) Error while downloading media: {e}")
                file_path = ""
        except Exception as e:
            logger.warning(f"(Sora) Error while processing detailed page media: {e}")
            media_url = ""
            final_filename = getattr(self.settings, "download_filename", "downloaded_media.webp")
            file_path = ""

        # Capture prompt
        prompt = ""
        try:
            prompt_button = self.wait.until(
                lambda d: d.find_element(By.XPATH, "//div[contains(text(),'Prompt')]/following-sibling::button")
            )
            prompt = prompt_button.text.strip()
        except Exception as e:
            logger.warning(f"(Sora) Prompt text not found: {e}")

        # Capture summary
        try:
            summary_element = self.wait.until(
                lambda d: d.find_element(By.XPATH, "//div[contains(@class, 'surface-nav-element')]//div[contains(@class, 'truncate') and not(ancestor::a)]")
            )
            summary = summary_element.text.strip()
        except Exception as e:
            logger.warning(f"(Sora) Summary text not found: {e}")
            summary = self.driver.title.strip()

        detailed_info = {
            "detailed_url": self.driver.current_url,
            "artist": artist,
            "summary": summary,
            "prompt": prompt,
            "media_url": media_url,
            "downloaded_media": final_filename
        }
        logger.info(f"(Sora) Captured detailed info: {detailed_info}")

        logger.info("(Sora) Returning to the previous page.")
        self.driver.back()
        time.sleep(1)  # Let the page revert
        self._state_transition(State.IDLE)

        return {
            "file_path": file_path,
            "media_type": media_type,
            "detailed_info": detailed_info
        }

    def _save_media(self, media_url, filename) -> str:
        download_dir = getattr(self.settings, "download_dir", "./explorer_downloads")
        os.makedirs(download_dir, exist_ok=True)
        file_path = os.path.join(download_dir, filename)
        try:
            response = requests.get(media_url, stream=True)
            response.raise_for_status()
            with open(file_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            logger.info(f"(Sora) Media saved to: {file_path}")
        except Exception as e:
            logger.error(f"(Sora) Failed to download media: {e}")
        return file_path

    def wait_for_duration(self, duration):
        self._state_transition(State.WAITING)
        logger.info(f"(Sora) Browser remaining open for {duration} second(s).")
        time.sleep(duration)
        self._state_transition(State.IDLE)

    def close(self):
        self._state_transition(State.CLOSING)
        if self.driver:
            try:
                self.driver.quit()
            except Exception as e:
                logger.info(f"(Sora) Driver quit encountered an error: {e}")
        self._state_transition(State.COMPLETED)

# -----------------------------
# API Implementation
# -----------------------------
_sora_opener = None
_plugin_manager = PluginManagerForSora()
_plugin_manager.register_plugin(LoggingPlugin())

def start_sora_explore_session() -> str:
    global _sora_opener
    if _sora_opener is not None:
        return "(Sora) Already started. Use 'stop' first if you want to restart."
    from bot_core.settings import settings
    _sora_opener = SimpleOpener(driver_path='chromedriver.exe', plugin_manager=_plugin_manager, settings=settings)
    _sora_opener.open_url()
    if KEEP_BROWSER_OPEN:
        _sora_opener.wait_for_duration(BROWSER_STAY_DURATION)
    return "(Sora) Browser launched and idle, ready for downloads."

async def download_sora_explore_session(ctx) -> dict | str:
    """
    Asynchronously triggers the download/capture process if a session is active and returns the file path for Discord delivery.

    Args:
        ctx: The Discord context (e.g., discord.Message or interaction). This is passed through unchanged; the API does not use it today, but may use it in the future for direct messaging or richer context.
        settings: Optionally override the Settings instance for this session.

    Returns:
        dict: { 'file_path': ... } on success
        str: Short error message on failure
    """
    global _sora_opener
    if _sora_opener is None:
        return "(Sora) No active session. Use 'start' to open a browser first."
    current_state = _sora_opener.state
    if current_state in [State.CLOSING, State.COMPLETED]:
        return "(Sora) Session is not available for downloads. Please start again."

    result = _sora_opener.capture_detailed_info()
    if not result.get("file_path"):
        return "(Sora) Download command executed, but no file was saved."
    return {"file_path": result["file_path"]}

def stop_sora_explore_session() -> str:
    global _sora_opener
    if _sora_opener is None:
        return "(Sora) No active session to stop."
    _sora_opener.close()
    _sora_opener = None
    return "(Sora) Browser closed."
    
def get_sora_explore_session_status() -> str:
    if _sora_opener is None:
        return "(Sora) No active session. Use 'start' to launch one."
    return f"(Sora) Current state: {_sora_opener.state.name}."

# End of core/api/sora_explore_api.py