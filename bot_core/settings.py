from pydantic_settings import BaseSettings
from typing import Optional, Dict
import sys

class Settings(BaseSettings):
    """
    Settings for the DiscordBot.
    
    Browser session config:
        chrome_profile_dir (env: CHROME_PROFILE_DIR)
        chrome_profile_name (env: CHROME_PROFILE_NAME)
        chromedriver_path (env: CHROMEDRIVER_PATH)
        browser_download_dir (env: BROWSER_DOWNLOAD_DIR)
    """
    discord_token: str
    db_name: str = "bot_data.db"
    backup_interval: int = 3600
    backup_retention: int = 10
    role_name_map: Dict[str, str] = {}
    gemini_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None

    # --- Browser session config ---
    chrome_profile_dir: Optional[str] = None
    chrome_profile_name: Optional[str] = "Profile 1"
    chromedriver_path: Optional[str] = None
    browser_download_dir: Optional[str] = "./browser_downloads"

    model_config = {
        "env_file": ".env",
        "case_sensitive": False,
        "extra": "allow"
    }

    def validate(self) -> None:
        """
        Run explicit, start-up-time checks that shouldn’t execute at import time.
        Extend this as new mandatory settings appear.
        """
        if not self.discord_token:
            raise RuntimeError(
                "DISCORD_TOKEN is required but not set. "
                "Define it in your environment or .env file."
            )

settings = Settings()

