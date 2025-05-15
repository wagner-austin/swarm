#!/usr/bin/env python
"""
managers/flow_manager.py
------------------------
Consolidated domain logic for multi-step volunteer flows and user states.
All flow and user state management is now centralized here, including welcome state.
"""

import logging
import json
from typing import Optional, Dict

from core.api import db_api

logger = logging.getLogger(__name__)

class FlowManager:
    """
    FlowManager - Encapsulates domain logic for multi-step flows
    and user state tracking.
    Exposes methods:
      - start_flow, pause_flow, resume_flow
      - get_active_flow, handle_flow_input, list_flows
      - has_seen_welcome, mark_welcome_seen
    All state operations are centralized here.
    """

    # --------------------------------------------------------
    # Public Flow Lifecycle Methods
    # --------------------------------------------------------
    def start_flow(self, user_id: str, flow_name: str):
        """
        Begin or reset the specified flow for the user, setting initial flow state.
        """
        self._create_flow(user_id, flow_name)

    def pause_flow(self, user_id: str, flow_name: str):
        """
        Temporarily pause the specified flow for the user.
        """
        self._pause_flow_state(user_id, flow_name)

    def resume_flow(self, user_id: str, flow_name: str):
        """
        Resume a previously paused flow for the user.
        """
        self._resume_flow_state(user_id, flow_name)

    def get_active_flow(self, user_id: str) -> Optional[str]:
        """
        Return the name of the flow the user is currently in, or None if none.
        """
        return self._get_active_flow_state(user_id)

    def handle_flow_input(self, user_id: str, user_input: str) -> str:
        """
        Process a piece of user input in the currently active flow (if any).
        Returns any user-facing response message.
        """
        flow_name = self.get_active_flow(user_id)
        if not flow_name:
            return ""
        logger.info(f"Unknown flow '{flow_name}' with input '{user_input}'. Pausing.")
        self.pause_flow(user_id, flow_name)
        return ""

    def list_flows(self, user_id: str) -> dict:
        """
        Return a dictionary with "active_flow" and "flows" from the user state.
        """
        user_state = self._load_flows_and_active(user_id)
        results = {}
        for flow_name, flow_info in user_state["flows"].items():
            results[flow_name] = {
                "step": flow_info.get("step"),
                "data_count": len(flow_info.get("data", {}))
            }
        return {
            "active_flow": user_state["active_flow"],
            "flows": results
        }

    # --------------------------------------------------------
    # Public Welcome-Tracking Methods
    # --------------------------------------------------------
    def has_seen_welcome(self, user_id: str) -> bool:
        """
        Return True if the user has previously seen the welcome message, otherwise False.
        """
        user_state = self._load_flows_and_active(user_id)
        return user_state.get("has_seen_start", False)

    def mark_welcome_seen(self, user_id: str) -> None:
        """
        Record that the user has now seen the welcome message.
        """
        user_state = self._load_flows_and_active(user_id)
        user_state["has_seen_start"] = True
        self._save_user_state(user_id, user_state)

    # --------------------------------------------------------
        # On the 'confirm' step, if user says 'delete', perform deletion.
        # Otherwise, cancel deletion.
    # Private Wrapper Methods for Flow State
    # --------------------------------------------------------
    def _create_flow(self, user_id: str, flow_name: str, start_step: str = "start", initial_data: dict = None):
        """
        Create or reset a flow in the user's state and make it active.
        """
        user_state = self._load_flows_and_active(user_id)
        user_state["flows"][flow_name] = {
            "step": start_step,
            "data": initial_data if initial_data else {}
        }
        user_state["active_flow"] = flow_name
        self._save_user_state(user_id, user_state)

    def _pause_flow_state(self, user_id: str, flow_name: str):
        user_state = self._load_flows_and_active(user_id)
        if user_state["active_flow"] == flow_name:
            user_state["active_flow"] = None
            self._save_user_state(user_id, user_state)

    def _resume_flow_state(self, user_id: str, flow_name: str):
        user_state = self._load_flows_and_active(user_id)
        if flow_name in user_state["flows"]:
            user_state["active_flow"] = flow_name
            self._save_user_state(user_id, user_state)

    def _get_active_flow_state(self, user_id: str) -> Optional[str]:
        user_state = self._load_flows_and_active(user_id)
        return user_state["active_flow"]

    def _get_flow_step(self, user_id: str, flow_name: str) -> str:
        user_state = self._load_flows_and_active(user_id)
        flow = user_state["flows"].get(flow_name)
        if not flow:
            return ""
        return flow.get("step", "")

    def _set_flow_step(self, user_id: str, flow_name: str, step: str):
        user_state = self._load_flows_and_active(user_id)
        flow = user_state["flows"].get(flow_name)
        if not flow:
            return
        flow["step"] = step
        self._save_user_state(user_id, user_state)

    # --------------------------------------------------------
    # Private User State Persistence
    # --------------------------------------------------------
    def _get_user_state_row(self, user_id: str) -> Optional[Dict[str, any]]:
        """
        Internal helper to retrieve the user's state row from the DB.
        Returns a dict or None.
        """
        query = "SELECT user_id, flow_state FROM UserStates WHERE user_id = ?"
        return db_api.fetch_one(query, (user_id,))

    def _save_user_state(self, user_id: str, state_data: dict) -> None:
        """
        Insert or update the user's state row in the DB.
        """
        encoded = json.dumps(state_data)
        existing = self._get_user_state_row(user_id)
        if existing:
            query = "UPDATE UserStates SET flow_state = ? WHERE user_id = ?"
            db_api.execute_query(query, (encoded, user_id), commit=True)
        else:
            data = {"user_id": user_id, "flow_state": encoded}
            db_api.insert_record("UserStates", data)

    def _load_flows_and_active(self, user_id: str) -> dict:
        """
        Parse the user's flow_state JSON into a dict with:
          { "flows": {...}, "active_flow": None or <flow_name> }
        """
        row = self._get_user_state_row(user_id)
        if not row:
            return {"flows": {}, "active_flow": None}
        try:
            parsed = json.loads(row["flow_state"])
            if not isinstance(parsed, dict):
                return {"flows": {}, "active_flow": None}
            if "flows" not in parsed or not isinstance(parsed["flows"], dict):
                parsed["flows"] = {}
            if "active_flow" not in parsed:
                parsed["active_flow"] = None
            return parsed
        except Exception:
            return {"flows": {}, "active_flow": None}

# End of managers/flow_manager.py