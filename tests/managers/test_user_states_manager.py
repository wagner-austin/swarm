#!/usr/bin/env python
"""
tests/managers/test_user_states_manager.py
------------------------------------------
Tests for flow-state management now that user_states_manager is removed.
We map old references to the flow_state_api / FlowManager as needed.
"""

import pytest
import concurrent.futures
from core.api.flow_state_api import (
    start_flow,
    pause_flow,
    resume_flow,
    get_active_flow,
    list_flows,
)
from managers.flow_manager import FlowManager

PHONE = "+1234567890"

def clear_flow_state(phone: str):
    """
    Overwrites the user's flow state to an empty structure, removing active flows.
    """
    FlowManager()._save_user_state(phone, {"flows": {}, "active_flow": None})


@pytest.fixture(autouse=True)
def cleanup_user_state():
    """Cleanup flow state after each test."""
    yield
    clear_flow_state(PHONE)


def test_create_and_get_flow_state():
    """Ensures start_flow sets the active flow, and get_active_flow reflects that."""
    clear_flow_state(PHONE)
    start_flow(PHONE, "registration")
    assert get_active_flow(PHONE) == "registration"


def test_clear_flow_state():
    """Verifies that clear_flow_state sets the active flow to None."""
    start_flow(PHONE, "edit")
    assert get_active_flow(PHONE) == "edit"
    clear_flow_state(PHONE)
    assert get_active_flow(PHONE) is None


def test_pause_flow():
    """Tests that pausing an active flow resets the active flow to None."""
    start_flow(PHONE, "registration")
    assert get_active_flow(PHONE) == "registration"
    pause_flow(PHONE, "registration")
    assert get_active_flow(PHONE) is None


def test_resume_flow():
    """Resumes a previously created flow so it becomes active again."""
    start_flow(PHONE, "registration")
    pause_flow(PHONE, "registration")
    resume_flow(PHONE, "registration")
    assert get_active_flow(PHONE) == "registration"


def test_list_flows_multiple():
    """Creates multiple flows and checks the listing."""
    start_flow(PHONE, "flow1")
    start_flow(PHONE, "flow2")
    flows_info = list_flows(PHONE)
    assert flows_info["active_flow"] == "flow2", "Latest created flow is active."
    assert "flow1" in flows_info["flows"], "Flow1 should be tracked."
    assert "flow2" in flows_info["flows"], "Flow2 should be tracked."


def test_concurrent_flow_modification():
    """
    Tests concurrency by modifying the same user's flows in multiple threads.
    The final active flow should be one of the concurrently created flows.
    """
    def flow_worker(flow_name):
        start_flow(PHONE, flow_name)

    flow_ops = ["flowA", "flowB", "flowC", "flowD"]

    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [executor.submit(flow_worker, fname) for fname in flow_ops]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    flows_info = list_flows(PHONE)
    active_flow = flows_info["active_flow"]
    assert active_flow in set(flow_ops), "Active flow must be one of the concurrently created flows."

# End of tests/managers/test_user_states_manager.py