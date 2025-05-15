#!/usr/bin/env python
"""
core/api/user_state_api.py
--------------------------
Stable User State API for plugin and manager developers.
Focuses on user-level flags and info that aren't specific to multi-step flows.
Internally calls managers.flow_manager for welcome-state tracking.

Usage Example:
    from bot_core.api.user_state_api import has_user_seen_welcome, mark_user_has_seen_welcome

    if not has_user_seen_welcome("+15551234567"):
        mark_user_has_seen_welcome("+15551234567")
"""





def has_user_seen_welcome(phone: str) -> bool:
    """
    has_user_seen_welcome(phone) -> bool
    ------------------------------------
    Returns True if the user has previously seen the welcome message, otherwise False.

    Usage Example:
        if has_user_seen_welcome("+15551234567"):
            print("User already saw the welcome message.")
        else:
            print("This is a new user.")
    """
    return _flow_manager.has_seen_welcome(phone)

def mark_user_has_seen_welcome(phone: str) -> None:
    """
    mark_user_has_seen_welcome(phone) -> None
    -----------------------------------------
    Record that this user has now seen the welcome message.

    Usage Example:
        mark_user_has_seen_welcome("+15551234567")
    """
    _flow_manager.mark_welcome_seen(phone)

# End of core/api/user_state_api.py