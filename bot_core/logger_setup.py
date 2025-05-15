"""
core/logger_setup.py - Provides a reusable logging configuration setup with robust handling.
This module centralizes logging configuration and exposes a setup_logging() function
that can be used in both production and testing environments.
"""

import logging
import logging.config
import copy
import warnings
from bot_core.utils.dict_tools import merge_dicts

DEFAULT_LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "%(asctime)s [%(levelname)s] %(message)s"
        },
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

def setup_logging(config_overrides=None):
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
    if not config.get("handlers") or not config["handlers"] or not config.get("root", {}).get("handlers"):
        warnings.warn("Logging configuration missing handlers; using fallback console handler.")
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