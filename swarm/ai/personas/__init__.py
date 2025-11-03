"""YAML-backed persona registry.

This package replaces the original hard-coded ``swarm.ai.personas`` module with a
flexible loader that

1. ships **built-in** personas in ``builtin.yaml`` (read-only, version-controlled),
2. merges **operator overrides** from ``~/.config/swarm/personas/*.yaml``
   (configurable via ``SWARM_PERSONA_DIR`` environment variable), and
3. exposes helper functions compatible with previous public API.

Unit-tests can monkey-patch ``SWARM_PERSONA_DIR`` before importing this module to
control the persona set.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Mapping, TypedDict, TypeGuard

import yaml  # PyYAML (dev dependency already present)
from discord.ext import commands

from swarm.core.settings import settings

__all__ = [
    "PERSONALITIES",
    "prompt",
    "visible",
    "visible_local",
    "Persona",
    # internal helpers exposed for tests / admin cog
    "_CUSTOM_DIR",
    "_load",
]

logger = logging.getLogger(__name__)


class Persona(TypedDict):
    prompt: str
    # allow list entries to be either int (YAML bare number) or str (quoted number)
    allowed_users: list[int | str] | None


class PersonaYaml(TypedDict, total=False):
    prompt: str
    allowed_users: list[int | str]


def _is_persona_yaml(value: object) -> TypeGuard[PersonaYaml]:
    if not isinstance(value, dict):
        return False
    prompt = value.get("prompt")
    if not isinstance(prompt, str):
        return False
    allowed = value.get("allowed_users")
    if allowed is not None:
        if not isinstance(allowed, list):
            return False
        for u in allowed:
            if not isinstance(u, int | str):
                return False
    return True


def _coerce(raw_map: Mapping[str, object]) -> dict[str, Persona]:
    """Return mapping with strict ``Persona`` objects.

    Ensures *prompt* exists and fills missing ``allowed_users`` with ``None`` so
    mypy's TypedDict requirements are satisfied.
    """

    result: dict[str, Persona] = {}
    for key, val in raw_map.items():
        if not _is_persona_yaml(val):
            continue
        prompt = val["prompt"]
        allowed = val.get("allowed_users") if isinstance(val.get("allowed_users"), list) else None
        result[key] = {"prompt": prompt, "allowed_users": allowed}
    return result


# ---------------------------------------------------------------------------
# Filesystem locations
# ---------------------------------------------------------------------------

_BASE_DIR: Path = Path(__file__).resolve().parent  # …/swarm/ai/personas
_BUILTIN_YAML: Path = _BASE_DIR / "builtin.yaml"

_CUSTOM_DIR: Path = Path(
    os.getenv(
        "SWARM_PERSONA_DIR",
        Path.home() / ".config" / "swarm" / "personas",
    )
).expanduser()

# ensure directory exists so admin cog can write immediately
try:
    _CUSTOM_DIR.mkdir(parents=True, exist_ok=True)
except PermissionError:
    # In Docker, might not have permission to create at module import
    pass

# extra secret location (never committed to git)
_SECRET_FILE: Path = _CUSTOM_DIR.parent / "secrets" / "personas.yaml"
# Make sure parent dir exists so admin upload can succeed at runtime
try:
    _SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
except PermissionError:
    # In Docker, might not have permission to create at module import
    pass


# ---------------------------------------------------------------------------
# Loading helpers
# ---------------------------------------------------------------------------


def _load(fp: Path) -> dict[str, Persona]:
    """Load *fp* if it exists; return an empty dict otherwise."""

    if not fp.exists():
        return {}

    raw_text: str = fp.read_text("utf-8")
    loaded: object = yaml.safe_load(raw_text) or {}
    if not isinstance(loaded, dict):
        return {}
    prepared: dict[str, object] = {str(k): v for k, v in loaded.items()}
    return _coerce(prepared)


# ---------------------------------------------------------------------------
# Internal loading helpers
# ---------------------------------------------------------------------------

PERSONALITIES: dict[str, Persona] = {}


def _populate(target: dict[str, Persona]) -> None:
    """(Re)fill *target* with merged YAML data."""

    target.clear()
    # built-ins first
    target.update(_load(_BUILTIN_YAML))

    # operator overrides (lexicographic override)
    for _file in sorted(_CUSTOM_DIR.glob("*.yaml")):
        target.update(_load(_file))

    # secrets from env before file so file wins (operator preference)
    # Check both SWARM_SECRET_PERSONAS and BOT_SECRET_PERSONAS (backward compatibility)
    _secret_env: str | None = os.getenv("SWARM_SECRET_PERSONAS") or os.getenv("BOT_SECRET_PERSONAS")
    if _secret_env:
        try:
            loaded_env: object = yaml.safe_load(_secret_env) or {}
            if isinstance(loaded_env, dict):
                target.update(_coerce({str(k): v for k, v in loaded_env.items()}))
        except Exception as exc:
            # Fail soft – malformed env secrets shouldn't crash the bot
            logger.warning(f"Failed to load personas from SWARM_SECRET_PERSONAS env: {exc}")

    # runtime secret file mounted by Fly (highest precedence)
    _runtime_secret_file: Path = Path("/secrets") / "SWARM_SECRET_PERSONAS"
    if _runtime_secret_file.exists():
        try:
            _runtime_raw: str = _runtime_secret_file.read_text("utf-8")
            loaded_file: object = yaml.safe_load(_runtime_raw) or {}
            if isinstance(loaded_file, dict):
                target.update(_coerce({str(k): v for k, v in loaded_file.items()}))
        except Exception as exc:
            logger.warning(
                f"Failed to load personas from runtime secret file {_runtime_secret_file}: {exc}"
            )

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


async def visible(name: str, user_id: int, bot: commands.Bot) -> bool:
    """Return *True* if *user_id* may use persona *name*.

    - If ``allowed_users`` is not set, the persona is public.
    - If ``allowed_users`` is set, the user must be in the list.
    - The special value ``${OWNER_ID}`` is resolved to the bot's owner.
    """
    from swarm.frontends.discord.discord_owner import get_owner  # late import

    persona = PERSONALITIES.get(name)
    if not persona:
        return False

    allowed = persona.get("allowed_users")
    if allowed is None:
        return True  # public

    # Resolve owner ID on-demand
    allowed_ids = set()
    if "${OWNER_ID}" in allowed:
        try:
            owner = await get_owner(bot)
            allowed_ids.add(str(owner.id))
        except RuntimeError:
            pass  # owner not resolvable, so can't match

    for uid in allowed:
        if uid != "${OWNER_ID}":
            allowed_ids.add(str(uid))

    return str(user_id) in allowed_ids


def visible_local(name: str, user_id: int, *, owner_id: int | None = None) -> bool:
    """Compute persona visibility without I/O.

    This is a efficient synchronous predicate intended for UI paths that must
    respond within strict time limits (e.g., Discord autocomplete). It mirrors
    :func:`visible` semantics using only the already-available inputs.

    Rules:
    - If the persona does not exist, return False.
    - If ``allowed_users`` is missing, the persona is public.
    - If ``allowed_users`` is present, allow when ``user_id`` matches, or when
      ``${OWNER_ID}`` is present and ``owner_id`` matches ``user_id``.
    """

    persona = PERSONALITIES.get(name)
    if not persona:
        return False

    allowed = persona.get("allowed_users")
    if allowed is None:
        return True

    user = str(user_id)
    allowed_strs = {str(x) for x in allowed}
    if user in allowed_strs:
        return True
    if owner_id is not None and "${OWNER_ID}" in allowed_strs and user == str(owner_id):
        return True
    return False


__all__ = ["PERSONALITIES", "prompt", "visible", "Persona"]
