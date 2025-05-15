#!/usr/bin/env python
"""
parsers/plugin_arg_parser.py - Pydantic-based plugin argument parser.
Provides typed Pydantic models and a unified validate_model function for argument validation.
Raises PluginArgError on invalid arguments.
"""

from typing import List, Type, TypeVar
from pydantic import BaseModel, ValidationError

# -----------------------------
# Exception for usage errors
# -----------------------------
class PluginArgError(Exception):
    """Custom exception raised when plugin argument parsing fails."""
    pass

# -----------------------------
# Volunteer Command Models
# -----------------------------
class VolunteerFindModel(BaseModel):
    """Used by 'find' command for searching volunteers by skills."""
    skills: List[str]

class VolunteerAddSkillsModel(BaseModel):
    """Used by 'add skills' command to add multiple skills to a volunteer."""
    skills: List[str]

# -----------------------------
# Unified model validation helper
# -----------------------------
T = TypeVar("T", bound=BaseModel)

def validate_model(data: dict, model: Type[T], usage: str) -> T:
    """
    validate_model - Validate a data dictionary against a Pydantic model.
    Raises PluginArgError with a uniform "Usage error:" message on validation failure.
    
    Args:
        data (dict): Data dictionary to validate.
        model (Type[BaseModel]): Pydantic model class.
        usage (str): Usage message to display in error.
    
    Returns:
        An instance of the model.
    
    Raises:
        PluginArgError: If validation fails.
    """
    try:
        return model.model_validate(data)
    except ValidationError as ve:
        raise PluginArgError(f"Usage error: {usage}\n{ve}")

# End of parsers/plugin_arg_parser.py