"""DEPRECATED – import directly from `bot_core.parsers`."""

import warnings
from bot_core.parsers import (
    parse_message,
    split_args,
    parse_key_value_args,
    SkillQueryModel,
    SkillListModel,
)

warnings.warn(__doc__, DeprecationWarning, stacklevel=2)

__all__ = [
    "parse_message",
    "split_args",
    "parse_key_value_args",
    "SkillQueryModel",
    "SkillListModel",
]
