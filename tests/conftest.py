#!/usr/bin/env python
# Add the src directory to the Python path for all tests

# Now import other modules
import pytest
import warnings
from typing import Any, Generator
from bot.core.logger_setup import setup_logging

# Silence noisy third-party deprecations we can’t fix locally.
warnings.filterwarnings(
    "ignore",
    message=r"(?i).*tagMap is deprecated.*",
    category=DeprecationWarning,
    module=r"pyasn1\.",
)
warnings.filterwarnings(
    "ignore",
    message=r"(?i).*typeMap is deprecated.*",
    category=DeprecationWarning,
    module=r"pyasn1\.",
)

"""
tests/conftest.py – test harness bootstrap.
Provides a CLI-runner; no DB fixtures remain.
"""


# --- Robust file-based test DB setup ---
# (fixture removed – no database)

# ------------------------------------------------------------------+
# Global logging setup                                              +
# ------------------------------------------------------------------+
setup_logging({"root": {"level": "WARNING"}})


@pytest.fixture
def cli_runner() -> Generator[Any, None, None]:
    """
    tests/conftest.py - Fixture for CLI command simulation.
    Provides a unified helper to simulate CLI command invocations of cli_tools.py.
    """
    from tests.cli.cli_test_helpers import run_cli_command

    yield run_cli_command
