#!/usr/bin/env python
"""
tests/conftest.py - Consolidated test fixtures and common setup for database isolation, CLI simulation, and plugin registration.
This module overrides DB_NAME for test isolation, clears key database tables, and provides common fixtures including a unified CLI runner.
"""

import sys
import os
# Insert the project root (one directory above tests) into sys.path to ensure modules like 'managers' are discoverable.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import tempfile
import pytest
import asyncio
import pathlib
import os
import pytest_asyncio
from bot_core.storage import acquire

# --- Robust file-based test DB setup ---
@pytest.fixture(scope="session", autouse=True)
def test_db_file():
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)
    db_url = f"sqlite+aiosqlite:///{db_path}"
    os.environ["DB_URL"] = db_url
    yield db_path
    os.remove(db_path)

from alembic.config import Config
from alembic import command

@pytest.fixture(scope="session", autouse=True)
def apply_migrations(test_db_file):
    alembic_ini = pathlib.Path(__file__).parents[1] / "alembic.ini"
    alembic_cfg = Config(str(alembic_ini))
    alembic_cfg.set_main_option("sqlalchemy.url", os.environ["DB_URL"])
    alembic_cfg.set_main_option("script_location", "migrations")
    command.upgrade(alembic_cfg, "head")


@pytest_asyncio.fixture(scope="function")
async def async_db():
    """
    Async fixture to yield an aiosqlite connection with in-memory DB.
    """
    async with acquire() as conn:
        yield conn

import pathlib
import pytest_asyncio
from bot_core.api import db_api
from alembic.config import Config
from alembic import command



@pytest_asyncio.fixture(scope="function", autouse=True)
async def reset_user_state():
    """
    Clear UserStates table between tests. Alembic migrations are already applied session-wide.
    """
    async def clear_user_states():
        row = await db_api.fetch_one("SELECT name FROM sqlite_master WHERE type='table' AND name='UserStates'")
        if row is not None:
            await db_api.execute_query("DELETE FROM UserStates", commit=True)
    await clear_user_states()
    yield
    await clear_user_states()


@pytest.fixture
def cli_runner():
    """
    tests/conftest.py - Fixture for CLI command simulation.
    Provides a unified helper to simulate CLI command invocations of cli_tools.py.
    """
    from tests.cli.cli_test_helpers import run_cli_command
    yield run_cli_command

import sys, types, pytest

@pytest.fixture(autouse=True, scope="function")
def patch_uc(monkeypatch):
    """Stub out undetected_chromedriver and the selenium import tree."""
    dummy_driver = types.SimpleNamespace(
        get=lambda *a, **k: None,
        save_screenshot=lambda path: True,
        quit=lambda: None,
    )
    dummy_wait = object()

    # --- undetected_chromedriver ------------------------------------------
    uc_mod = types.ModuleType("undetected_chromedriver")
    uc_mod.ChromeOptions = lambda: types.SimpleNamespace(
        add_experimental_option=lambda *a, **k: None,
        add_argument=lambda *a, **k: None,
    )
    uc_mod.Chrome = lambda *a, **k: dummy_driver
    monkeypatch.setitem(sys.modules, "undetected_chromedriver", uc_mod)

    # --- selenium.webdriver.support.ui ------------------------------------
    sel_mod  = types.ModuleType("selenium")
    wd_mod   = types.ModuleType("selenium.webdriver")
    supp_mod = types.ModuleType("selenium.webdriver.support")
    ui_mod   = types.ModuleType("selenium.webdriver.support.ui")
    ui_mod.WebDriverWait = lambda *a, **k: dummy_wait

    supp_mod.ui = ui_mod
    wd_mod.support = supp_mod
    sel_mod.webdriver = wd_mod

    monkeypatch.setitem(sys.modules, "selenium", sel_mod)
    monkeypatch.setitem(sys.modules, "selenium.webdriver", wd_mod)
    monkeypatch.setitem(sys.modules, "selenium.webdriver.support", supp_mod)
    monkeypatch.setitem(sys.modules, "selenium.webdriver.support.ui", ui_mod)
    yield

# End of tests/conftest.py