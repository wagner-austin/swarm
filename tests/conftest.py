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

# ------------------------------------------------------------------+
# Global Playwright headless override (safety in CI)                 +
# ------------------------------------------------------------------+

# Ensure every test run keeps the browser headless and invisible to
# avoid accidental UI launches (especially in CI environments).


# Type annotated autouse fixture (required by --strict mypy)
@pytest.fixture(autouse=True)
def _force_headless(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force Playwright to run headless for the entire test session."""

    # Patch the global settings object if it exists. `raising=False` means
    # the attribute will be created if missing, so this works even if the
    # settings module gets imported lazily during tests.
    monkeypatch.setattr(
        "bot.core.settings.settings.browser.headless", True, raising=False
    )
    monkeypatch.setattr(
        "bot.core.settings.settings.browser.visible", False, raising=False
    )


@pytest.fixture
def cli_runner() -> Generator[Any, None, None]:
    """
    tests/conftest.py - Fixture for CLI command simulation.
    Provides a unified helper to simulate CLI command invocations of cli_tools.py.
    """
    from tests.cli.cli_test_helpers import run_cli_command

    yield run_cli_command
