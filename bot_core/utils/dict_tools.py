"""
bot_core.utils.dict_tools
-------------------------
Small, generic helpers for manipulating dictionaries.

Currently only `merge_dicts()`, extracted from logger_setup so it can be reused
by any module (including tests) without duplicating code.
"""
from __future__ import annotations
import warnings
from typing import Any, Mapping, MutableMapping

def merge_dicts(base: MutableMapping[str, Any],
                overrides: Mapping[str, Any]) -> MutableMapping[str, Any]:
    """
    Recursively merge *overrides* into *base*.

    * For nested dicts, values are merged depth-first.  
    * If the types at the same key differ, the override value wins and a
      `warnings.warn()` is emitted (same behaviour the old copies had).

    Returns the modified *base* for convenience so callers can write
    `cfg = merge_dicts(cfg, overrides)`.
    """
    for key, value in overrides.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            merge_dicts(base[key], value)
        else:
            if key in base and not isinstance(base[key], type(value)):
                warnings.warn(
                    f"Type mismatch for key '{key}': "
                    f"{type(base[key]).__name__} vs {type(value).__name__}. "
                    "Using override value."
                )
            base[key] = value
    return base
