"""
core/logger_setup.py - Provides a reusable logging configuration setup with robust handling.
This module centralizes logging configuration and exposes a setup_logging() function
that can be used in both production and testing environments.
"""

import collections
import copy
import logging
import logging.config
import os
import warnings
from typing import Any


def merge_dicts(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """
    Recursively merge *overrides* into *base*.

    * For nested dicts, values are merged depth-first.
    * If the types at the same key differ, the override value wins and a
      `warnings.warn()` is emitted (same behaviour the old copies had).

    Returns the modified *base* for convenience so callers can write
    `cfg = merge_dicts(cfg, overrides)`.
    """
    for key, value in overrides.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            merge_dicts(base[key], value)
        else:
            if key in base and not isinstance(base[key], type(value)):
                warnings.warn(
                    f"Type mismatch for key '{key}': "
                    f"{type(base[key]).__name__} vs {type(value).__name__}. "
                    "Using override value."
                )
            base[key] = value
    return base


DEFAULT_LOGGING_CONFIG: dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        # RichHandler ignores most format string except datefmt,
        # keep formatter minimal and pass only datefmt.
        "rich": {"datefmt": "%Y-%m-%d %H:%M:%S"},
        "default": {"format": "%(asctime)s [%(levelname)s] %(message)s"},
    },
    "filters": {"dedupe": {"()": "bot.core.logger_setup._DuplicateFilter"}},
    "handlers": {
        "rich": {
            "class": "rich.logging.RichHandler",
            "markup": True,
            "rich_tracebacks": True,
            "show_path": False,
            "formatter": "rich",
            "filters": ["dedupe"],
        },
    },
    "root": {
        "handlers": ["rich"],
        "level": "INFO",
    },
}


# Sentinel to avoid multiple configuration attempts
# Suppress duplicate exception log entries in quick succession (same message & traceback)
class _DuplicateFilter(logging.Filter):
    """Filter that drops consecutive duplicate (msg, exc_text) records."""

    def __init__(self, window: int = 20) -> None:
        super().__init__()
        self._recent: collections.deque[tuple[str, str]] = collections.deque(maxlen=window)

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        key = (record.getMessage(), getattr(record, "exc_text", ""))
        if key in self._recent:
            return False
        self._recent.append(key)
        return True


_CONFIGURED: bool = False


def setup_logging(config_overrides: dict[str, Any] | None = None) -> None:
    """
    setup_logging - Configures logging using a centralized configuration.

    Args:
        config_overrides (dict, optional): A dictionary with logging configuration overrides.
            This can be used to modify the default logging setup for different environments.

    Returns:
        None
    """
    # Modern approach – rely on ``dictConfig(force=True)`` to wipe any pre-existing
    # handlers instead of manual loops.
    global _CONFIGURED
    if _CONFIGURED:
        return  # already configured – avoid duplicate handlers

    config = copy.deepcopy(DEFAULT_LOGGING_CONFIG)

    # Honour LOG_LEVEL env variable (e.g. DEBUG, INFO, WARNING)
    env_level = os.getenv("LOG_LEVEL")
    if env_level:
        config.setdefault("root", {})["level"] = env_level.upper()
    # Ensure force is set so *all* previous handlers are removed in one go.
    config["force"] = True
    if config_overrides:
        merge_dicts(config, config_overrides)

    # Check for empty or missing handlers in overall config or in the root logger.
    if (
        not config.get("handlers")
        or not config["handlers"]
        or not config.get("root", {}).get("handlers")
    ):
        warnings.warn("Logging configuration missing handlers; using fallback console handler.")
        config["handlers"] = {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
            },
        }
        if "root" in config:
            config["root"]["handlers"] = ["console"]

    # Apply final configuration now that defaults are ensured.
    logging.config.dictConfig(config)
    _CONFIGURED = True


# End of core/logger_setup.py
