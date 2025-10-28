# ruff: noqa: E402
#!/usr/bin/env python
# Add the src directory to the Python path for all tests

import os
from urllib.parse import urlparse

from dotenv import load_dotenv

# IMPORTANT: Configure Celery singleton BEFORE any imports
load_dotenv()

password = os.getenv("REDIS_PASSWORD", "")
auth_part = f"default:{password}@" if password else ""


def _is_localhost_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return host in {"localhost", "127.0.0.1", "haproxy-redis"}


def _looks_production(url: str) -> bool:
    lu = url.lower()
    if "upstash.io" in lu or "production" in lu:
        return True
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    # Treat any non-local host as production-like for safety
    return host not in {"", "localhost", "127.0.0.1", "haproxy-redis"}


# Use HAProxy for consistency with production, but do not override a pre-set
# production-like REDIS_URL to allow safety checks to trigger in tests.
BROKER = f"redis://{auth_part}localhost:6380/0"

pre_set_url = os.getenv("REDIS_URL", "")
# Respect an explicitly provided test DB (e.g., /15). Do not override to BROKER.
if not pre_set_url:
    # IMPORTANT: Use DB 0 via HAProxy so the router can find session affinity keys
    # that workers store. Router uses Settings().redis.url to connect, workers use
    # CELERY_BROKER_URLS. Both must point to the same DB for affinity routing to work.
    os.environ["REDIS_URL"] = BROKER

# Always configure Celery to talk through HAProxy for production parity
os.environ["CELERY_BROKER_URL"] = BROKER
os.environ["CELERY_BROKER_URLS"] = BROKER

# Now import everything else
import asyncio
import warnings
from collections.abc import AsyncGenerator, Generator
from typing import Any
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from swarm.core.logger_setup import setup_logging
from swarm.core.settings import Settings

# Configure Redis URLs for tests
# This ensures all tests have proper authentication from .env file
password = os.getenv("REDIS_PASSWORD", "")
if password:
    # Always use authenticated URLs for Celery broker when password is set
    auth_part = f"default:{password}@"
    os.environ["CELERY_BROKER_URLS"] = f"redis://{auth_part}localhost:6380/0"
    os.environ["CELERY_BROKER_URL"] = f"redis://{auth_part}localhost:6380/0"

    # Also set the password separately for tests building their own URLs
    os.environ["REDIS_PASSWORD"] = password

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
# Clear cached state between tests                                   +
# ------------------------------------------------------------------+
@pytest.fixture(autouse=True)
def clear_worker_lifecycle_cache() -> Generator[None, None, None]:
    """Clear WorkerLifecycle cache before each test to prevent cross-contamination.

    WorkerLifecycle has a class-level instance cache that persists across tests.
    This can cause DB isolation issues when tests use different Redis DBs.
    """
    from swarm.distributed.worker_lifecycle import WorkerLifecycle

    # Clear cache before test
    WorkerLifecycle._instances.clear()

    yield

    # Clear cache after test to prevent leaks
    WorkerLifecycle._instances.clear()


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


# Note: Flushdb runtime guard has been extracted to scripts/guard_flushdb_runtime.py
# and is installed by the Makefile test wrapper before pytest starts.


# Type annotated autouse fixture (required by --strict mypy)
@pytest_asyncio.fixture(autouse=True)
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


@pytest.fixture
def cli_runner() -> Generator[Any, None, None]:
    """
    tests/conftest.py - Fixture for CLI command simulation.
    Provides a unified helper to simulate CLI command invocations of cli_tools.py.
    """
    from tests.cli.cli_test_helpers import run_cli_command

    yield run_cli_command
