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

# Immediately override DB_NAME for tests before any other modules are imported.
fd, temp_db_path = tempfile.mkstemp(prefix="bot_data_test_", suffix=".db")
os.close(fd)
os.environ["DB_NAME"] = temp_db_path

@pytest.fixture(scope="session", autouse=True)
def test_database():
    """
    tests/conftest.py - Creates and initializes a temporary database for testing.
    The DB_NAME environment variable is set to a temporary file for isolation.
    After tests, the temporary database file is removed and DB_NAME is unset.
    """
    import db.schema
    db.schema.init_db()
    yield
    try:
        os.remove(temp_db_path)
    except Exception:
        pass
    os.environ.pop("DB_NAME", None)

@pytest.fixture(scope="session", autouse=True)
def reset_user_state():
    """
    Fixture to initialize the DB schema once per test session and reset UserStates between tests.
    Mirrors the Discord-centric schema and keeps tests independent.
    """
    import db.schema
    db.schema.init_db()
    from db.connection import get_connection
    def clear_user_states():
        conn = get_connection()
        cursor = conn.cursor()
        # Check if UserStates table exists before attempting to delete
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='UserStates'")
        if cursor.fetchone() is not None:
            cursor.execute("DELETE FROM UserStates")
            conn.commit()
        conn.close()
    clear_user_states()
    yield
    clear_user_states()

@pytest.fixture
def dummy_plugin():
    """
    tests/conftest.py - Fixture for dummy plugin registration.
    Registers a dummy plugin in plugins.manager.plugin_registry and unregisters it after the test.
    """
    from plugins.manager import plugin_registry
    dummy_plugin_data = {
        "function": lambda args, sender, state_machine, msg_timestamp=None: "yes",
        "aliases": ["test"],
        "help_visible": True,
    }
    plugin_registry["test"] = dummy_plugin_data
    yield dummy_plugin_data
    plugin_registry.pop("test", None)

@pytest.fixture
def cli_runner():
    """
    tests/conftest.py - Fixture for CLI command simulation.
    Provides a unified helper to simulate CLI command invocations of cli_tools.py.
    """
    from tests.cli.cli_test_helpers import run_cli_command
    yield run_cli_command

import sys, types, pytest

@pytest.fixture(autouse=True)
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