#!/usr/bin/env python
# Add the src directory to the Python path for all tests
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

# Now import other modules
import types
import pytest
import pytest_asyncio
from alembic.config import Config
from alembic import command
import tempfile
import pathlib
import os
from typing import Any, Generator, AsyncGenerator
from src.bot_core.api import db_api
from src.bot_core.storage import acquire

"""
tests/conftest.py - Consolidated test fixtures and common setup for database isolation, CLI simulation, and plugin registration.
This module overrides DB_NAME for test isolation, clears key database tables, and provides common fixtures including a unified CLI runner.
"""


# --- Robust file-based test DB setup ---
@pytest.fixture(scope="session", autouse=True)
def test_db_file() -> Generator[pathlib.Path, None, None]:
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)
    db_path_obj = pathlib.Path(db_path)
    db_url = f"sqlite+aiosqlite:///{db_path_obj.as_posix()}"
    os.environ["DB_URL"] = db_url
    yield db_path_obj
    db_path_obj.unlink()


@pytest.fixture(scope="session", autouse=True)
def apply_migrations(test_db_file: Path) -> Generator[None, None, None]:
    alembic_ini = pathlib.Path(__file__).parents[1] / "alembic.ini"
    alembic_cfg = Config(str(alembic_ini))
    alembic_cfg.set_main_option("sqlalchemy.url", os.environ["DB_URL"])
    alembic_cfg.set_main_option("script_location", "src/migrations")
    command.upgrade(alembic_cfg, "head")
    yield


@pytest_asyncio.fixture(scope="function")
async def async_db() -> AsyncGenerator[Any, None]:
    """
    Async fixture to yield an aiosqlite connection with in-memory DB.
    """
    async with acquire() as conn:
        yield conn


@pytest_asyncio.fixture(scope="function", autouse=True)
async def reset_user_state() -> AsyncGenerator[None, None]:
    """
    Clear UserStates table between tests. Alembic migrations are already applied session-wide.
    """

    async def clear_user_states() -> None:
        row = await db_api.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='UserStates'"
        )
        if row is not None:
            await db_api.execute_query("DELETE FROM UserStates", commit=True)

    await clear_user_states()
    yield
    await clear_user_states()


@pytest.fixture(autouse=True)  # default = function scope
def patch_uc(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Always stub undetected_chromedriver and the selenium import tree for tests.
    The dummy driver is only activated if BROWSER_HEADLESS is unset or truthy (mirrors production startup).
    """
    import os

    def get_func(*a: Any, **k: Any) -> None:
        return None

    def save_screenshot_func(path: Any) -> bool:
        return True

    def quit_func() -> None:
        return None

    dummy_driver = types.SimpleNamespace(
        get=get_func,
        save_screenshot=save_screenshot_func,
        quit=quit_func,
    )
    dummy_wait = object()

    # --- undetected_chromedriver ------------------------------------------
    uc_mod = types.ModuleType("undetected_chromedriver")
    setattr(uc_mod, "__all__", ["ChromeOptions", "Chrome"])

    # Silence undetected_chromedriver logger
    import logging

    uc_log = logging.getLogger("undetected_chromedriver")
    uc_log.propagate = False
    uc_log.addHandler(logging.NullHandler())

    def add_experimental_option_func(*a: Any, **k: Any) -> None:
        return None

    def add_argument_func(*a: Any, **k: Any) -> None:
        return None

    def chrome_options_func() -> Any:
        return types.SimpleNamespace(
            add_experimental_option=add_experimental_option_func,
            add_argument=add_argument_func,
        )

    def chrome_func(*a: Any, **k: Any) -> Any:
        # Only use the dummy driver if BROWSER_HEADLESS is unset or truthy
        headless_env = os.environ.get("BROWSER_HEADLESS", "true").lower()
        if headless_env in ("1", "true", "yes", "on", ""):  # default True
            return dummy_driver
        # If not headless, simulate a real driver (could be another dummy or raise)
        return types.SimpleNamespace(
            get=get_func,
            save_screenshot=save_screenshot_func,
            quit=quit_func,
            real=True,  # marker for test
        )

    setattr(uc_mod, "ChromeOptions", chrome_options_func)
    setattr(uc_mod, "Chrome", chrome_func)
    monkeypatch.setitem(sys.modules, "undetected_chromedriver", uc_mod)

    # --- selenium.webdriver.support.ui ------------------------------------
    sel_mod = types.ModuleType("selenium")
    wd_mod = types.ModuleType("selenium.webdriver")
    supp_mod = types.ModuleType("selenium.webdriver.support")
    ui_mod = types.ModuleType("selenium.webdriver.support.ui")
    setattr(sel_mod, "__all__", ["webdriver"])
    setattr(wd_mod, "__all__", ["support"])
    setattr(supp_mod, "__all__", ["ui"])
    setattr(ui_mod, "__all__", ["WebDriverWait"])

    def webdriver_wait_func(*a: Any, **k: Any) -> Any:
        return dummy_wait

    setattr(ui_mod, "WebDriverWait", webdriver_wait_func)

    setattr(supp_mod, "ui", ui_mod)
    setattr(wd_mod, "support", supp_mod)
    setattr(sel_mod, "webdriver", wd_mod)

    monkeypatch.setitem(sys.modules, "selenium", sel_mod)
    monkeypatch.setitem(sys.modules, "selenium.webdriver", wd_mod)
    monkeypatch.setitem(sys.modules, "selenium.webdriver.support", supp_mod)
    monkeypatch.setitem(sys.modules, "selenium.webdriver.support.ui", ui_mod)


@pytest.fixture
def cli_runner() -> Generator[Any, None, None]:
    """
    tests/conftest.py - Fixture for CLI command simulation.
    Provides a unified helper to simulate CLI command invocations of cli_tools.py.
    """
    from tests.cli.cli_test_helpers import run_cli_command

    yield run_cli_command
