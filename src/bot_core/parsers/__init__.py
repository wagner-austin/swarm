"""
parsers/__init__.py
-------------------
Parsers package for the personal Discord bot. Provides message parsing utilities for extracting key information from incoming messages.

Note: import directly from bot_core.parsers – all legacy alias modules have been removed.
"""

from pydantic import BaseModel
import warnings
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


# Deprecation aliases for backward compatibility
class _VolunteerFindModel(SkillQueryModel):
    def __new__(cls, *args: object, **kwargs: object) -> "_VolunteerFindModel":
        warnings.warn(
            "VolunteerFindModel is deprecated; use SkillQueryModel instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return super().__new__(cls)


class _VolunteerAddSkillsModel(SkillListModel):
    def __new__(cls, *args: object, **kwargs: object) -> "_VolunteerAddSkillsModel":
        warnings.warn(
            "VolunteerAddSkillsModel is deprecated; use SkillListModel instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return super().__new__(cls)


VolunteerFindModel = _VolunteerFindModel
VolunteerAddSkillsModel = _VolunteerAddSkillsModel
