from __future__ import annotations

import pytest

from swarm.core.cogs_registry import (
    OPTIONAL_DI_COGS,
    REQUIRED_DI_COGS,
    validate_registry,
)
from swarm.core.containers import Container


def test_cogs_registry_validates_against_container() -> None:
    """Smoke test: registry stays consistent with container providers."""
    container = Container()
    # Should not raise
    validate_registry(container)


def test_plugin_keys_are_unique() -> None:
    """Ensure plugin_key values are unique across all DI-managed cogs."""
    keys = [
        spec.plugin_key
        for spec in (list(REQUIRED_DI_COGS) + list(OPTIONAL_DI_COGS))
        if spec.plugin_key
    ]
    assert len(keys) == len(set(keys))
