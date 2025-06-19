"""Tests for bot.utils.module_discovery.iter_submodules()."""

from importlib import import_module
from types import ModuleType
from typing import List

import pytest

from bot.utils.module_discovery import iter_submodules


@pytest.mark.asyncio
async def test_iter_submodules_returns_leaf_modules() -> None:
    """Ensure iter_submodules yields expected leaf module names for bot.plugins.commands."""

    pkg_name = "bot.plugins.commands"
    # Collect discovered modules
    discovered: list[str] = list(iter_submodules(pkg_name))

    # Sanity: There should be at least one command module.
    assert discovered, "iter_submodules() returned an empty list for commands package"

    # Spot-check a few known commands that should always exist
    expected = {
        "bot.plugins.commands.about",
        "bot.plugins.commands.chat",
    }

    missing = expected.difference(discovered)
    assert not missing, f"Expected modules not discovered: {', '.join(sorted(missing))}"
