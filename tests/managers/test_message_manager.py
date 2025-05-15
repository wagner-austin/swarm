#!/usr/bin/env python
"""
tests/managers/test_message_manager.py
--------------------------------------
Ensures process_message delegates to plugin commands or FlowManager when a user is in
an active flow, and that direct dispatch testing (fuzzy matching, group command parsing)
also works. Includes step-by-step tests for registration, edit, and deletion flows.
"""

import pytest
from managers.message_manager import MessageManager
from managers.message.message_dispatcher import dispatch_message as handle_message
from core.state import BotStateMachine
from parsers.message_parser import ParsedMessage, parse_message
from managers.flow_manager import FlowManager
from core.api.flow_state_api import (
    start_flow,
    get_active_flow
)
from db.volunteers import delete_volunteer_record


def clear_flow_state(phone: str):
    """
    Resets the user's flow state locally by overwriting with an empty dictionary.
    """
    FlowManager()._save_user_state(phone, {"flows": {}, "active_flow": None})


# -------------------------------------------------------------------------
# Shared Fixtures and Helpers
# -------------------------------------------------------------------------
@pytest.fixture
def dummy_phone():
    return "+1111111111"


@pytest.fixture
def message_manager():
    state_machine = BotStateMachine()
    return MessageManager(state_machine)


@pytest.fixture(autouse=True)
def cleanup_user_flow(dummy_phone):
    """
    Cleanup flow state and volunteer record after each multi-flow test.
    """
    yield
    clear_flow_state(dummy_phone)
    delete_volunteer_record(dummy_phone)


class DummyVolunteerManager:
    """
    A minimal volunteer manager for tests that do not require
    the real manager logic (e.g., fuzzy matching or group parsing).
    """
    def delete_volunteer(self, sender: str) -> str:
        return "deleted"

    def sign_up(self, sender: str, name: str, skills: list) -> str:
        return "dummy response"

    def volunteer_status(self):
        return "status ok"


def make_dummy_parsed_message() -> ParsedMessage:
    """
    Creates a dummy ParsedMessage with command "dummy" and no arguments.
    """
    return ParsedMessage(
        sender="+1111111111",
        body="@bot dummy",
        timestamp=123,
        group_id=None,
        reply_to=None,
        message_timestamp=None,
        command="dummy",
        args=""
    )


def _make_parsed(sender, command=None, body="", timestamp=999):
    """
    Helper to create a ParsedMessage with optional command, body, and timestamp.
    """
    return ParsedMessage(
        sender=sender,
        body=body,
        timestamp=timestamp,
        group_id=None,
        reply_to=None,
        message_timestamp=None,
        command=command,
        args=None if command is None else ""
    )


def make_envelope_message(body: str, sender: str = "+1234567890", group_id: str = None) -> ParsedMessage:
    """
    Helper function (originally from test_handle_message.py) to create a
    real envelope string and parse it into a ParsedMessage.
    """
    envelope = f"from: {sender}\nBody: {body}\nTimestamp: 123\n"
    if group_id:
        envelope += f"Group info: {group_id}\n"
    return parse_message(envelope)


# ----------------------------------------------------------------------------
# Tests from test_handle_message.py that are unique to dispatch_message
# ----------------------------------------------------------------------------
@pytest.fixture
def volunteer_status_plugin(monkeypatch):
    """
    Fixture for a 'volunteer status' plugin used to test group trailing text.
    """
    from plugins.manager import plugin_registry, alias_mapping
    alias_mapping["volunteer status"] = "volunteer status"

    def dummy_volunteer_status(args, sender, state_machine, msg_timestamp=None):
        return f"status: {args}"

    plugin_registry["volunteer status"] = {
        "function": dummy_volunteer_status,
        "aliases": ["volunteer status"],
        "help_visible": True
    }
    yield
    alias_mapping.pop("volunteer status", None)
    plugin_registry.pop("volunteer status", None)


def test_handle_message_fuzzy_matching():
    """
    Test that a near-miss command ("tset") is fuzzy-matched correctly.
    We assume the fuzzy match leads to "dummy" => "dummy response".
    """
    parsed = make_envelope_message("@bot tset", sender="+111")
    state_machine = BotStateMachine()
    response = handle_message(parsed, "+111", state_machine, DummyVolunteerManager(), msg_timestamp=123)
    # Our fixture or logic might respond with "dummy response"
    assert response in ["dummy response", "yes"], (
        "Expected fuzzy match to yield either 'dummy response' or 'yes'."
    )


def test_group_command_with_extra_text(volunteer_status_plugin):
    """
    Test that a group message with extra trailing text after the recognized command
    correctly extracts the command "volunteer status" and arguments "extra nonsense".
    """
    parsed = make_envelope_message("@bot volunteer status extra nonsense", sender="+1111111111", group_id="group123")
    state_machine = BotStateMachine()
    dummy_vol_manager = DummyVolunteerManager()

    response = handle_message(parsed, parsed.sender, state_machine, dummy_vol_manager, msg_timestamp=123)

    assert parsed.command == "volunteer status"
    assert parsed.args == "extra nonsense"
    assert response == "status: extra nonsense"


# ----------------------------------------------------------------------------
# Existing tests from test_message_manager.py
# ----------------------------------------------------------------------------
def test_message_manager_process_message(message_manager):
    """
    Test that MessageManager.process_message dispatches the dummy command correctly.
    The response should be "dummy response".
    """
    parsed = make_dummy_parsed_message()
    volunteer_manager = DummyVolunteerManager()
    response = message_manager.process_message(parsed, parsed.sender, volunteer_manager, msg_timestamp=123)
    assert response == "dummy response"


def test_no_command_no_active_flow(message_manager, dummy_phone):
    """
    If there's no recognized command and no active flow, the response should be empty.
    """
    parsed = ParsedMessage(
        sender=dummy_phone,
        body="random text here",
        timestamp=123,
        group_id=None,
        reply_to=None,
        message_timestamp=None,
        command=None,
        args=None
    )
    response = message_manager.process_message(parsed, dummy_phone, volunteer_manager=None)
    assert response == "", "No command + no active flow => empty response"


def test_active_flow_auto_dispatch(message_manager, dummy_phone):
    """
    If the user has an active flow, a message with no recognized command
    should be auto-dispatched to the flow logic (stub or real).
    """
    start_flow(dummy_phone, "testflow")
    parsed = ParsedMessage(
        sender=dummy_phone,
        body="some message",
        timestamp=999,
        group_id=None,
        reply_to=None,
        message_timestamp=None,
        command=None,
        args=None
    )
    response = message_manager.process_message(parsed, dummy_phone, volunteer_manager=None)
    # By default, the FlowManager doesn't handle "testflow" specifically, so we get an empty response
    assert response == ""


def test_command_takes_precedence(message_manager, dummy_phone):
    """
    If there's a recognized command, it should override the active flow,
    and the recognized command's plugin response should be returned.
    """
    start_flow(dummy_phone, "flowA")
    parsed = ParsedMessage(
        sender=dummy_phone,
        body="@bot dummy",
        timestamp=111,
        group_id=None,
        reply_to=None,
        message_timestamp=None,
        command="dummy",
        args=""
    )
    response = message_manager.process_message(parsed, dummy_phone, volunteer_manager=None)
    assert response == "dummy response"
    assert get_active_flow(dummy_phone) == "flowA"


def test_registration_flow_step_by_step(message_manager, dummy_phone):
    """
    Test the volunteer registration flow from start to end.
    1) The user issues '@bot register'
    2) The user responds with a valid full name or 'skip'
    3) Final outcome is a successful registration.
    """
    parsed1 = _make_parsed(dummy_phone, command="register", body="@bot register")
    response1 = message_manager.process_message(parsed1, dummy_phone, volunteer_manager=None)
    assert "starting registration flow." in response1.lower()

    parsed2 = _make_parsed(dummy_phone, body="My Name")
    response2 = message_manager.process_message(parsed2, dummy_phone, volunteer_manager=None)
    assert "registered" in response2.lower() or "volunteer" in response2.lower()


def test_edit_flow_step_by_step(message_manager, dummy_phone):
    """
    Test the volunteer edit flow from start to end.
    1) Ensure user is first registered
    2) The user issues '@bot edit'
    3) The user sends new name => flow completes
    """
    parsed_reg1 = _make_parsed(dummy_phone, command="register", body="@bot register")
    _ = message_manager.process_message(parsed_reg1, dummy_phone, volunteer_manager=None)
    parsed_reg2 = _make_parsed(dummy_phone, body="skip")
    _ = message_manager.process_message(parsed_reg2, dummy_phone, volunteer_manager=None)

    parsed1 = _make_parsed(dummy_phone, command="edit", body="@bot edit")
    response1 = message_manager.process_message(parsed1, dummy_phone, volunteer_manager=None)
    assert "starting edit flow." in response1.lower()

    parsed2 = _make_parsed(dummy_phone, body="MyNewName")
    response2 = message_manager.process_message(parsed2, dummy_phone, volunteer_manager=None)
    assert "updated" in response2.lower() or "registered" in response2.lower()


def test_deletion_flow_step_by_step(message_manager, dummy_phone):
    """
    Test the volunteer deletion flow from start to finish.
    1) Register
    2) Issue '@bot delete'
    3) type 'yes' => confirm
    4) type 'delete' => done
    """
    parsed_reg1 = _make_parsed(dummy_phone, command="register", body="@bot register")
    _ = message_manager.process_message(parsed_reg1, dummy_phone, volunteer_manager=None)
    parsed_reg2 = _make_parsed(dummy_phone, body="skip")
    _ = message_manager.process_message(parsed_reg2, dummy_phone, volunteer_manager=None)

    parsed_delete_init = _make_parsed(dummy_phone, command="delete", body="@bot delete")
    response_init = message_manager.process_message(parsed_delete_init, dummy_phone, volunteer_manager=None)
    assert "starting deletion flow." in response_init.lower()

    parsed_yes = _make_parsed(dummy_phone, body="yes")
    response_yes = message_manager.process_message(parsed_yes, dummy_phone, volunteer_manager=None)
    assert "type 'delete'" in response_yes.lower()

    parsed_confirm = _make_parsed(dummy_phone, body="delete")
    response_confirm = message_manager.process_message(parsed_confirm, dummy_phone, volunteer_manager=None)
    assert "deleted" in response_confirm.lower()

# End of tests/managers/test_message_manager.py