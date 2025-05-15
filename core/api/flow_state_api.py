#!/usr/bin/env python
"""
core/api/flow_state_api.py
--------------------------
Stable façade for multi-step flows. Delegates all flow operations to the centralized FlowManager.
"""

import logging
from typing import Optional

from managers.flow_manager import FlowManager

logger = logging.getLogger(__name__)
_flow_manager = FlowManager()

def start_flow(user_id: str, flow_name: str) -> None:
    """
    Begin or reset the specified flow for the user by delegating to FlowManager.
    """
    _flow_manager.start_flow(user_id, flow_name)

def pause_flow(user_id: str, flow_name: str) -> None:
    """
    Pause the specified flow for the user by delegating to FlowManager.
    """
    _flow_manager.pause_flow(user_id, flow_name)

def resume_flow(user_id: str, flow_name: str) -> None:
    """
    Resume a previously paused flow for the user by delegating to FlowManager.
    """
    _flow_manager.resume_flow(user_id, flow_name)

def get_active_flow(user_id: str) -> Optional[str]:
    """
    Return the name of the active flow for the user, or None if none, by delegating to FlowManager.
    """
    return _flow_manager.get_active_flow(user_id)

def handle_flow_input(user_id: str, user_input: str) -> str:
    """
    Process a piece of user input in the active flow (if any) by delegating to FlowManager.
    Returns any user-facing response message.
    """
    return _flow_manager.handle_flow_input(user_id, user_input)

def list_flows(user_id: str) -> dict:
    """
    Return a dictionary containing the active flow and all flows for the user,
    by delegating to FlowManager.
    """
    return _flow_manager.list_flows(user_id)

# End of core/api/flow_state_api.py