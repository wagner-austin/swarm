from pydantic_settings import BaseSettings
from typing import Optional, Dict
import sys

class Settings(BaseSettings):
    discord_token: str
    db_name: str = "bot_data.db"
    backup_interval: int = 3600
    backup_retention: int = 10
    role_name_map: Dict[str, str] = {}
    gemini_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None

    model_config = {
        "env_file": ".env",
        "case_sensitive": False,
        "extra": "allow"
    }

settings = Settings()

if not settings.discord_token:
    raise RuntimeError("DISCORD_TOKEN is required in the environment or .env file.")
