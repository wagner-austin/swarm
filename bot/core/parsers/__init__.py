"""
parsers/__init__.py
-------------------
Parsers package for the personal Discord bot. Provides message parsing utilities for extracting key information from incoming messages.

Note: import directly from bot_core.parsers – all legacy alias modules have been removed.
"""

from pydantic import BaseModel
from ._helpers import split_args, parse_key_value_args, parse_message

__all__: list[str] = [
    "split_args",
    "parse_key_value_args",
    "parse_message",
    "SkillQueryModel",
    "SkillListModel",
]


class SkillQueryModel(BaseModel):
    """Used for searching by skills."""

    skills: list[str]


class SkillListModel(BaseModel):
    """Used to add multiple skills."""

    skills: list[str]
