#!/usr/bin/env python
"""
tests/plugins/test_flow_plugin.py
---------------------------------
Tests for the 'flow' plugin commands: list, switch, pause, create.
"""

import pytest
from plugins.manager import get_plugin
from core.api.flow_state_api import get_active_flow  # Updated import

@pytest.fixture
def dummy_sender():
    return "+12223334444"

def test_flow_list_no_flows(dummy_sender):
    """
    If user has no flows, @bot flow list should show none.
    """
    flow_plugin = get_plugin("flow")
    response = flow_plugin("list", dummy_sender, None)
    assert "Active Flow: None" in response, "No flows yet means no active flow"

def test_flow_create_then_list(dummy_sender):
    """
    After creating a flow, it should become active and appear in flow list.
    """
    flow_plugin = get_plugin("flow")
    flow_plugin("create testflow", dummy_sender, None)
    response = flow_plugin("list", dummy_sender, None)
    assert "Active Flow: testflow" in response
    # The default step is 'start'
    assert "- testflow (step=start" in response, "Default step for create_flow is 'start'"

def test_flow_switch(dummy_sender):
    """
    Create multiple flows, switch among them, verify active_flow changes.
    """
    flow_plugin = get_plugin("flow")
    flow_plugin("create flowA", dummy_sender, None)
    flow_plugin("create flowB", dummy_sender, None)
    # flowB is active now
    list_cmd_response = flow_plugin("list", dummy_sender, None)
    assert "Active Flow: flowB" in list_cmd_response

    # Switch to flowA
    flow_plugin("switch flowA", dummy_sender, None)
    assert get_active_flow(dummy_sender) == "flowA"

def test_flow_pause(dummy_sender):
    """
    Pause the active flow, check that active_flow is None afterwards.
    """
    flow_plugin = get_plugin("flow")
    flow_plugin("create testflow", dummy_sender, None)
    assert get_active_flow(dummy_sender) == "testflow"

    flow_plugin("pause", dummy_sender, None)
    assert get_active_flow(dummy_sender) is None

def test_flow_pause_specific(dummy_sender):
    """
    Pause a named flow that was active, confirm it's paused.
    """
    flow_plugin = get_plugin("flow")
    flow_plugin("create myFlow", dummy_sender, None)
    assert get_active_flow(dummy_sender) == "myFlow"

    flow_plugin("pause myFlow", dummy_sender, None)
    assert get_active_flow(dummy_sender) is None, "Should have no active flow after pause"

def test_unknown_subcommand(dummy_sender):
    """
    Passing an unknown subcommand to flow plugin should return an error string.
    """
    flow_plugin = get_plugin("flow")
    response = flow_plugin("foobar something", dummy_sender, None)
    assert "Unknown subcommand" in response

# End of tests/plugins/test_flow_plugin.py