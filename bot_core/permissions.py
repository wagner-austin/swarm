#!/usr/bin/env python
"""
core/permissions.py
-------------------
Centralizes role-based permission logic for the volunteer system, ensuring a
unified and consistent approach for future updates.

Focuses on modular, unified, consistent code that facilitates future changes.
"""

# IMPORTANT: role *values* are always lower‑case; use the constants below
# everywhere instead of hard‑coding strings like "ADMIN" or "owner".
# Role Constants
OWNER = "owner"
ADMIN = "admin"
MEMBER = "member"
EVERYONE = "everyone"

# Internal hierarchy to compare roles easily:
_ROLE_HIERARCHY = {
    OWNER: 3,
    ADMIN: 2,
    MEMBER: 1,
    EVERYONE: 0,
}

def has_permission(user_role: str, required_role: str) -> bool:
    """
    has_permission(user_role, required_role) -> bool
    ------------------------------------------------
    Returns True if user_role meets or exceeds the required_role in the hierarchy.

    Example:
        if has_permission("admin", "member"):
            # admin has permission to do tasks restricted to members
            ...
    """
    user_rank = _ROLE_HIERARCHY.get(user_role, _ROLE_HIERARCHY[EVERYONE])
    required_rank = _ROLE_HIERARCHY.get(required_role, _ROLE_HIERARCHY[EVERYONE])
    return user_rank >= required_rank

# End of core/permissions.py