#!/usr/bin/env python
"""
core/config.py - Centralized configuration for the Signal bot.
Loads configuration settings from environment variables with default values.
"""

from warnings import warn
from bot_core.settings import settings  # noqa: F401
warn("bot_core.config is deprecated; use bot_core.settings", DeprecationWarning, stacklevel=2)

# Check if .env file exists; if not, log info. Otherwise, load it.
dotenv_path = os.path.join(os.getcwd(), '.env')
if not os.path.exists(dotenv_path):
    logger.info(f"No .env found at {dotenv_path}, skipping environment file load.")
else:
    load_dotenv(dotenv_path)

# Database name for SQLite, defaulting to "bot_data.db" if not set.
DB_NAME: str = os.environ.get("DB_NAME", "bot_data.db")

# Map Discord role names to bot roles (loaded from environment)
def _parse_role_name_map():
    val = os.environ.get("ROLE_NAME_MAP", '{}')
    try:
        return json.loads(val)
    except Exception as e:
        logger.warning(f"Failed to parse ROLE_NAME_MAP from env: {e}. Using empty map.")
        return {}
ROLE_NAME_MAP = _parse_role_name_map()

# Backup interval in seconds (default 3600 seconds = 1 hour),
# safely parse int to handle corrupted or non-numeric values.
BACKUP_INTERVAL: int = parse_int_env(
    os.environ.get("BACKUP_INTERVAL", "3600"),
    3600,
    "BACKUP_INTERVAL"
)

# Number of backup snapshots to retain (default 10), for disk backup retention
DISK_BACKUP_RETENTION_COUNT: int = int(os.getenv("DISK_BACKUP_RETENTION_COUNT", 10))

# For backward compatibility; canonical backup interval
DISK_BACKUP_INTERVAL = BACKUP_INTERVAL

# === API Keys ===
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# End of config.py