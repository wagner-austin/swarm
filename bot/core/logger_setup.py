"""
core/logger_setup.py - Provides a reusable logging configuration setup with robust handling.
This module centralizes logging configuration and exposes a setup_logging() function
that can be used in both production and testing environments.
"""

from typing import Optional, Dict, Any
import logging
import logging.config
import copy
import warnings


def merge_dicts(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
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


DEFAULT_LOGGING_CONFIG: Dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {"format": "%(asctime)s [%(levelname)s] %(message)s"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}


def setup_logging(config_overrides: Optional[Dict[str, Any]] = None) -> None:
    """
    setup_logging - Configures logging using a centralized configuration.

    Args:
        config_overrides (dict, optional): A dictionary with logging configuration overrides.
            This can be used to modify the default logging setup for different environments.

    Returns:
        None
    """
    config = copy.deepcopy(DEFAULT_LOGGING_CONFIG)
    if config_overrides:
        merge_dicts(config, config_overrides)

    # Check for empty or missing handlers in overall config or in the root logger.
    if (
        not config.get("handlers")
        or not config["handlers"]
        or not config.get("root", {}).get("handlers")
    ):
        warnings.warn(
            "Logging configuration missing handlers; using fallback console handler."
        )
        config["handlers"] = {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
            },
        }
        if "root" in config:
            config["root"]["handlers"] = ["console"]

    logging.config.dictConfig(config)


# End of core/logger_setup.py
