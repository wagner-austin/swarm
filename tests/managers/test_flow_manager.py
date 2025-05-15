#!/usr/bin/env python
"""
tests/managers/test_flow_manager.py
-----------------------------------
Negative & edge-case coverage for volunteer deletion flow. Ensures that
'not registered' logic, confirmation steps, and multi-flow scenarios
work correctly.
"""

import pytest
from managers.flow_manager import FlowManager, DELETION_FLOW
from db.volunteers import add_volunteer_record, delete_volunteer_record

def clear_flow_state(phone: str):
    """
    Local helper to reset the user's flow state.
    """
    FlowManager()._save_user_state(phone, {"flows": {}, "active_flow": None})

@pytest.fixture
def mock_phone():
    return "+9998887771"

@pytest.fixture
def flow_manager():
    return FlowManager()

@pytest.fixture(autouse=True)
def cleanup_flows(mock_phone):
    """
    Ensures flow state and volunteer record are cleared after each test.
    """
    yield
    clear_flow_state(mock_phone)
    delete_volunteer_record(mock_phone)

def test_already_deleted_user_deletion_flow(mock_phone, flow_manager):
    """
    If the user is not in Volunteers or is already deleted,
    the flow's first input should see that record is None and return the
    correct 'not registered' message.
    """
    delete_volunteer_record(mock_phone)  # ensure user is not in Volunteers
    flow_manager.start_flow(mock_phone, DELETION_FLOW)

    response = flow_manager.handle_flow_input(mock_phone, "delete")
    # The updated flow manager returns: "You are not currently registered; nothing to delete."
    assert "not currently registered" in response.lower()

def test_contradictory_first_step(mock_phone, flow_manager):
    """
    Test user providing random text at the initial flow step => 'Deletion cancelled.'
    """
    add_volunteer_record(mock_phone, "DeletionFlowTest", ["FlowSkill"], True, None)
    flow_manager.start_flow(mock_phone, DELETION_FLOW)

    r1 = flow_manager.handle_flow_input(mock_phone, "randomstuff")
    assert "deletion cancelled" in r1.lower()

def test_confirm_step_cancelled(mock_phone, flow_manager):
    """
    Once user says 'yes' in the initial step => confirm step.
    If they then type random text => 'Deletion cancelled.'
    """
    add_volunteer_record(mock_phone, "DeletionFlowTest2", [], True, None)
    flow_manager.start_flow(mock_phone, DELETION_FLOW)

    flow_manager.handle_flow_input(mock_phone, "yes")  # next step => confirm
    r3 = flow_manager.handle_flow_input(mock_phone, "nope")
    assert "deletion cancelled" in r3.lower()

def test_confirm_step_proceeds(mock_phone, flow_manager):
    """
    Normal path: user eventually says 'delete' at confirm => record is deleted.
    """
    add_volunteer_record(mock_phone, "DeletionFlowTest3", [], True, None)
    flow_manager.start_flow(mock_phone, DELETION_FLOW)

    flow_manager.handle_flow_input(mock_phone, "yes")  # initial => confirm
    r3 = flow_manager.handle_flow_input(mock_phone, "delete")
    assert "deleted" in r3.lower()

def test_multiple_flows_same_user(mock_phone, flow_manager):
    """
    Starting a second flow overwrites the active flow for that user.
    """
    add_volunteer_record(mock_phone, "DeletionFlowTest4", [], True, None)
    flow_manager.start_flow(mock_phone, DELETION_FLOW)

    active1 = flow_manager.get_active_flow(mock_phone)
    assert active1 == DELETION_FLOW

    # Then create another flow forcibly
    flow_manager.start_flow(mock_phone, "some_other_flow")
    active2 = flow_manager.get_active_flow(mock_phone)
    assert active2 == "some_other_flow"

# End of tests/managers/test_flow_manager.py