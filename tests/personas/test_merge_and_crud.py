"""Unit-tests for YAML-backed persona registry and admin CRUD helpers."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest

# Target module under test
from swarm.ai import personas as p

# ---------------------------------------------------------------------------
# Helper to reload the personas module with a temporary custom directory
# ---------------------------------------------------------------------------


def _reload_with_dir(tmp_dir: Path) -> Any:  # noqa: ANN401 – dynamic import
    """Reload ``swarm.ai.personas`` with ``SWARM_PERSONA_DIR`` set to *tmp_dir*."""

    import os
    from importlib import reload

    os.environ["SWARM_PERSONA_DIR"] = str(tmp_dir)
    return reload(p)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_merge_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Custom YAML should override built-in personas **lexicographically**."""

    custom_dir = tmp_path / "personas"
    custom_dir.mkdir()

    # Two override files – 'aaa' then 'zzz' for deterministic order
    (custom_dir / "zzz.yaml").write_text("pirate:\n  prompt: NEW1\n", "utf-8")
    (custom_dir / "aaa.yaml").write_text("pirate:\n  prompt: NEW2\n", "utf-8")

    # Ensure module reads from our temp dir
    monkeypatch.setenv("SWARM_PERSONA_DIR", str(custom_dir))
    importlib.reload(p)

    # Lexicographically later (zzz) should win
    assert p.prompt("pirate") == "NEW1"


def test_crud(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PersonaAdmin helpers should update both disk and in-memory registry."""

    monkeypatch.setenv("SWARM_PERSONA_DIR", str(tmp_path))
    importlib.reload(p)

    # Import persona_admin after reload so it picks up patched _CUSTOM_DIR
    from swarm.plugins.commands import persona_admin as adm

    importlib.reload(adm)

    # Patch internal _CUSTOM_DIR used by adm helper (for safety)
    adm._CUSTOM_DIR = tmp_path  # type: ignore[attr-defined]

    # Simulate `/persona add` via helper
    adm._write_yaml("foo", {"prompt": "bar", "allowed_users": None})

    assert p.prompt("foo") == "bar"

    # Simulate delete via helper
    adm._delete_yaml("foo")

    assert "foo" not in p.PERSONALITIES
