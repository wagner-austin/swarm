"""YAML-backed persona registry.

This package replaces the original hard-coded ``bot.ai.personas`` module with a
flexible loader that

1. ships **built-in** personas in ``builtin.yaml`` (read-only, version-controlled),
2. merges **operator overrides** from ``~/.config/discord-bot/personas/*.yaml``
   (configurable via ``BOT_PERSONA_DIR`` environment variable), and
3. exposes helper functions compatible with previous public API.

Unit-tests can monkey-patch ``BOT_PERSONA_DIR`` before importing this module to
control the persona set.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional, TypedDict, Any

import yaml  # PyYAML (dev dependency already present)


from bot.core.settings import settings

__all__ = [
    "PERSONALITIES",
    "prompt",
    "visible",
    "Persona",
    # internal helpers exposed for tests / admin cog
    "_CUSTOM_DIR",
    "_load",
]


class Persona(TypedDict):
    prompt: str
    # allow list entries to be either int (YAML bare number) or str (quoted number)
    allowed_users: Optional[List[int | str]]


def _coerce(raw_map: Any) -> Dict[str, Persona]:
    """Return mapping with strict ``Persona`` objects.

    Ensures *prompt* exists and fills missing ``allowed_users`` with ``None`` so
    mypy's TypedDict requirements are satisfied.
    """

    result: Dict[str, Persona] = {}
    for key, val in dict(raw_map).items():
        if not isinstance(val, dict) or "prompt" not in val:
            # skip invalid entries quietly (matches earlier leniency)
            continue
        prompt: str = str(val["prompt"])
        allowed: Optional[List[int | str]] = val.get("allowed_users")
        result[key] = {"prompt": prompt, "allowed_users": allowed}
    return result


# ---------------------------------------------------------------------------
# Filesystem locations
# ---------------------------------------------------------------------------

_BASE_DIR: Path = Path(__file__).resolve().parent  # …/bot/ai/personas
_BUILTIN_YAML: Path = _BASE_DIR / "builtin.yaml"

_CUSTOM_DIR: Path = Path(
    os.getenv(
        "BOT_PERSONA_DIR",
        Path.home() / ".config" / "discord-bot" / "personas",
    )
).expanduser()

# ensure directory exists so admin cog can write immediately
_CUSTOM_DIR.mkdir(parents=True, exist_ok=True)

# extra secret location (never committed to git)
_SECRET_FILE: Path = _CUSTOM_DIR.parent / "secrets" / "personas.yaml"
# Make sure parent dir exists so admin upload can succeed at runtime
_SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Loading helpers
# ---------------------------------------------------------------------------


def _load(fp: Path) -> Dict[str, Persona]:
    """Load *fp* if it exists; return an empty dict otherwise."""

    if not fp.exists():
        return {}

    raw: str = fp.read_text("utf-8")
    # interpolate owner ID placeholder – allow empty fallback so yaml parses
    raw = raw.replace("${OWNER_ID}", str(settings.owner_id or ""))

    data: Any = yaml.safe_load(raw) or {}
    # ensure structure – mypy will validate below cast
    return _coerce(data)


# ---------------------------------------------------------------------------
# Internal loading helpers
# ---------------------------------------------------------------------------

PERSONALITIES: Dict[str, Persona] = {}


def _populate(target: Dict[str, Persona]) -> None:
    """(Re)fill *target* with merged YAML data."""

    target.clear()
    # built-ins first
    target.update(_load(_BUILTIN_YAML))

    # operator overrides (lexicographic override)
    for _file in sorted(_CUSTOM_DIR.glob("*.yaml")):
        target.update(_load(_file))

    # secrets from env before file so file wins (operator preference)
    _secret_env: str | None = os.getenv("BOT_SECRET_PERSONAS")
    if _secret_env:
        try:
            _env_raw: str = _secret_env.replace(
                "${OWNER_ID}", str(settings.owner_id or "")
            )
            target.update(_coerce(yaml.safe_load(_env_raw) or {}))
        except Exception:
            # Fail soft – malformed env secrets shouldn't crash the bot
            pass

    # runtime secret file mounted by Fly (highest precedence)
    _runtime_secret_file: Path = Path("/secrets") / "BOT_SECRET_PERSONAS"
    if _runtime_secret_file.exists():
        try:
            _runtime_raw: str = _runtime_secret_file.read_text("utf-8").replace(
                "${OWNER_ID}", str(settings.owner_id or "")
            )
            target.update(_coerce(yaml.safe_load(_runtime_raw) or {}))
        except Exception:
            pass

    # operator secrets file (local dev) – precedence just below runtime secret
    if _SECRET_FILE.exists():
        target.update(_load(_SECRET_FILE))


# initial population at import time
_populate(PERSONALITIES)


# ---------------------------------------------------------------------------
# Public hot-reload API
# ---------------------------------------------------------------------------


def refresh() -> None:  # pragma: no cover – exercised via admin cog at runtime
    """Reload all YAML sources into the existing *PERSONALITIES* dict."""

    _populate(PERSONALITIES)


# ---------------------------------------------------------------------------
# Public helpers – keep the old names so existing imports work
# ---------------------------------------------------------------------------


def prompt(name: str, *, default: str | None = None) -> str:
    """Return the persona’s prompt.

    If *name* is missing and *default* is given, that value is returned instead
    of propagating :class:`KeyError`.
    """

    try:
        return PERSONALITIES[name]["prompt"]
    except KeyError:
        if default is not None:
            return default
        raise


def visible(name: str, user_id: int) -> bool:
    """Return *True* if *user_id* may use persona *name*.

    Missing persona ➜ *False* (avoids unexpected ``KeyError``).
    """

    persona = PERSONALITIES.get(name)
    if persona is None:
        return False
    allowed = persona.get("allowed_users")
    # accept both ints and strings for user IDs to tolerate quoted YAML scalars in Fly secrets
    return allowed is None or str(user_id) in (str(uid) for uid in allowed)


__all__ = ["PERSONALITIES", "prompt", "visible", "Persona"]
