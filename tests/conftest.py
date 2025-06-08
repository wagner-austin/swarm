#!/usr/bin/env python
# Add the src directory to the Python path for all tests
import sys

# Now import other modules
import types
import pytest
import warnings
import os
from typing import Any, Generator

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
Provides UC/selenium stubs and a CLI-runner; no DB fixtures remain.
"""


# --- Robust file-based test DB setup ---
# (fixture removed – no database)


@pytest.fixture(autouse=True)  # default = function scope
def patch_uc(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Always stub undetected_chromedriver and the selenium import tree for tests.
    The dummy driver is only activated if BROWSER_HEADLESS is unset or truthy (mirrors production startup).
    """

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
