#!/usr/bin/env python
"""
core/config.py - Centralized configuration for the Signal bot.
Loads configuration settings from environment variables with default values.
"""

import os
import logging
import json
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


def parse_int_env(value_str: str, default: int, var_name: str) -> int:
    """
    parse_int_env(value_str: str, default: int, var_name: str) -> int
    Safely parse an integer from a string environment variable.

    If parsing fails, logs a warning and returns the provided default.

    Args:
        value_str (str): The string value from environment to parse.
        default (int): Default integer to return if parsing fails.
        var_name (str): Name of the environment variable (for logging).

    Returns:
        int: The parsed integer or the default on error.
    """
    try:
        return int(value_str)
    except (ValueError, TypeError):
        logger.warning(
            f"Invalid integer value for {var_name}: {value_str!r}. "
            f"Using default {default}."
        )
        return default

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