#!/usr/bin/env python
"""
core/serialization_utils.py
---------------------------
Provides functions for serializing/deserializing lists to/from comma-separated strings.
(Removed unify_skills_preserving_earliest, now in managers.volunteer_skills_manager.py)
"""

def serialize_list(items: list) -> str:
    """
    Convert a list of strings into a comma-separated string.
    
    Args:
        items (list): List of strings.
        
    Returns:
        str: Comma-separated string.
    """
    return ",".join(items)


def deserialize_list(serialized: str) -> list:
    """
    Convert a comma-separated string into a list of strings.
    
    Args:
        serialized (str): Comma-separated string.
        
    Returns:
        list: List of strings.
    """
    if not serialized:
        return []
    return [item.strip() for item in serialized.split(",") if item.strip()]

# End of core/serialization_utils.py