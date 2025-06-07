"""
Settings for the DiscordBot. All browser flags live in Settings.browser (see BrowserConfig).
"""

from pydantic_settings import BaseSettings
from pydantic import BaseModel, field_validator
from typing import Optional
from typing import TYPE_CHECKING, Any


class BrowserConfig(BaseModel):
    headless: bool = True
    disable_gpu: bool = True
    window_size: str = "1920,1080"
    no_sandbox: bool = True

    model_config = {"extra": "ignore"}


class Settings(BaseSettings):
    if TYPE_CHECKING:  # pragma: no cover

        def __init__(self, **data: Any) -> None: ...

    """
    Settings for the DiscordBot.
    
    Browser session config:
        chrome_profile_dir (env: CHROME_PROFILE_DIR)
        chrome_profile_name (env: CHROME_PROFILE_NAME)
        chromedriver_path (env: CHROMEDRIVER_PATH)
        browser_download_dir (env: BROWSER_DOWNLOAD_DIR)
    Browser flags live in Settings.browser (see BrowserConfig).
    """
    discord_token: str
    db_name: str = "bot_data.db"
    backup_interval: int = 3600
    backup_retention: int = 10
    gemini_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None

    # --- Browser session config ---
    chrome_profile_dir: Optional[str] = None
    chrome_profile_name: Optional[str] = "Profile 1"
    chromedriver_path: Optional[str] = None
    browser_download_dir: Optional[str] = "./browser_downloads"

    browser: BrowserConfig = BrowserConfig()

    model_config = {"env_file": ".env", "case_sensitive": False, "extra": "allow"}

    @field_validator("discord_token")
    @classmethod
    def _must_exist(cls, v: str) -> str:
        # Reject only truly empty/placeholder tokens
        placeholder = {"", "YOUR_TOKEN_HERE"}
        if v in placeholder:
            raise ValueError("DISCORD_TOKEN is required")
        return v

    @field_validator("db_name")
    @classmethod
    def _sqlite_file(cls, v: str) -> str:
        if not v.endswith(".db"):
            raise ValueError("DB_NAME must point to a *.db SQLite file")
        return v


# Export a singleton but fall back to a dummy token during static analysis
try:
    settings: "Settings" = Settings()  # real env-driven instance
except ValueError:  # DISCORD_TOKEN missing under CI / mypy
    settings = Settings(discord_token="dummy")

__all__ = ["Settings", "BrowserConfig"]
