#!/usr/bin/env python
# Add the src directory to the Python path for all tests

import asyncio
import warnings
from collections.abc import AsyncGenerator, Generator
from typing import Any
from unittest.mock import MagicMock

import pytest

from bot.core.logger_setup import setup_logging
from bot.core.settings import Settings

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


@pytest.fixture
def mock_settings() -> Settings:
    """
    Robust Settings mock for all integration/startup tests.
    Covers all attributes accessed during bot lifecycle startup.
    If you add new required settings, update this fixture!
    """
    settings = MagicMock(spec=Settings)
    settings.discord_token = "fake_token"
    settings.owner_id = 123456789
    settings.metrics_port = 0
    settings.gemini_api_key = None
    settings.openai_api_key = None
    settings.conversation_max_turns = 8
    settings.discord_chunk_size = 1900
    settings.gemini_model = "gemini-2.5-flash-preview-04-17"
    settings.personalities_file = None
    # Proxy settings
    settings.proxy_enabled = False
    settings.proxy_port = None
    settings.proxy_cert_dir = ".mitm_certs"
    settings.proxy = MagicMock()
    settings.proxy.enabled = False
    # Browser settings
    settings.chrome_profile_dir = None
    settings.chrome_profile_name = "Profile 1"
    settings.chromedriver_path = None
    settings.browser_download_dir = None
    settings.browser_version_main = None
    settings.browser = MagicMock()
    settings.browser.headless = False
    settings.browser.visible = True
    settings.browser.read_only = False
    settings.browser.proxy_enabled = False
    # Queue settings
    settings.queues = MagicMock()
    settings.queues.inbound = 500
    settings.queues.outbound = 200
    settings.queues.command = 100
    settings.queues.alerts = 200
    # Redis settings
    settings.redis = MagicMock()
    settings.redis.enabled = False
    settings.redis.url = None
    # Security and observability
    settings.allowed_hosts = []
    return settings


# Type annotated autouse fixture (required by --strict mypy)
@pytest.fixture(autouse=True)
async def _cleanup_asyncio_tasks() -> AsyncGenerator[None, None]:
    """Ensure no pending tasks survive beyond each test function.

    pytest-asyncio closes the event loop *after* test teardown.  If background
    tasks spawned inside a test are still running, the loop closure logs
    warnings like "Task was destroyed but it is pending".  We pre-emptively
    cancel and await any leftover tasks so they finish cleanly.
    """
    # Run the test.
    yield

    # After the test function returns, cancel remaining tasks.
    loop = asyncio.get_running_loop()
    pending: list[asyncio.Task[Any]] = [
        t
        for t in asyncio.all_tasks(loop)
        if t is not asyncio.current_task(loop=loop) and not t.done()
    ]
    for task in pending:
        task.cancel()
    if pending:
        # Await their cancellation but ignore CancelledError results.
        await asyncio.gather(*pending, return_exceptions=True)


# Type annotated autouse fixture (required by --strict mypy)
@pytest.fixture(autouse=True)
def _force_headless(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force Playwright to run headless for the entire test session."""

    # Patch the global settings object if it exists. `raising=False` means
    # the attribute will be created if missing, so this works even if the
    # settings module gets imported lazily during tests.
    monkeypatch.setattr("bot.core.settings.settings.browser.headless", True, raising=False)
    monkeypatch.setattr("bot.core.settings.settings.browser.visible", False, raising=False)


@pytest.fixture
def cli_runner() -> Generator[Any, None, None]:
    """
    tests/conftest.py - Fixture for CLI command simulation.
    Provides a unified helper to simulate CLI command invocations of cli_tools.py.
    """
    from tests.cli.cli_test_helpers import run_cli_command

    yield run_cli_command
