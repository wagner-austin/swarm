"""
File: tests/plugins/test_volunteer_commands.py
---------------------------------------------
Tests volunteer command plugins. Ensures normal usage for register, edit, delete, etc.,
and verifies that when a volunteer record is missing, the response directs the user properly.
"""

from core.state import BotStateMachine
from db.volunteers import get_volunteer_record
from plugins.messages import REGISTRATION_WELCOME
from plugins.manager import get_plugin

def test_volunteer_register_new():
    """
    Tests registering a brand new volunteer with arguments.
    """
    register_plugin = get_plugin("register")
    phone = "+80000000001"
    state_machine = BotStateMachine()
    response = register_plugin("default Test User", phone, state_machine, msg_timestamp=123)
    assert "registered" in response.lower()
    record = get_volunteer_record(phone)
    assert record is not None
    assert record.get("name").lower() == "test user"

def test_volunteer_register_existing():
    """
    Tests attempting to register again if the volunteer is already registered.
    """
    register_plugin = get_plugin("register")
    phone = "+80000000002"
    state_machine = BotStateMachine()
    register_plugin("default Existing User", phone, state_machine, msg_timestamp=123)
    response = register_plugin("default Any Name", phone, state_machine, msg_timestamp=123)
    # "already registered" path from the flow
    assert "you are already registered as" in response.lower()

def test_volunteer_register_no_args_shows_welcome():
    """
    Tests that when a new volunteer sends no arguments and no record exists,
    the registration welcome message is returned.
    """
    register_plugin = get_plugin("register")
    phone = "+80000000009"
    state_machine = BotStateMachine()
    response = register_plugin("default", phone, state_machine, msg_timestamp=123)
    assert REGISTRATION_WELCOME in response

def test_volunteer_edit_command_interactive():
    """
    Tests that editing with no arguments initiates interactive name editing.
    """
    register_plugin = get_plugin("register")
    edit_plugin = get_plugin("edit")

    phone = "+80000000003"
    state_machine = BotStateMachine()
    register_plugin("default Initial Name", phone, state_machine, msg_timestamp=123)
    response = edit_plugin("default", phone, state_machine, msg_timestamp=123)
    assert "starting edit flow" in response.lower() or "please provide your new name" in response.lower()

def test_volunteer_delete_command():
    """
    Tests volunteer deletion with no arguments -> should set a deletion flow state.
    """
    register_plugin = get_plugin("register")
    delete_plugin = get_plugin("delete")

    phone = "+80000000004"
    state_machine = BotStateMachine()
    register_plugin("default Delete Me", phone, state_machine, msg_timestamp=123)
    response = delete_plugin("default", phone, state_machine, msg_timestamp=123)
    assert ("delete" in response.lower()) or ("starting deletion flow" in response.lower())

def test_volunteer_skills_command():
    """
    Tests the skills command, which lists current skills and potential additions.
    """
    register_plugin = get_plugin("register")
    skills_plugin = get_plugin("skills")

    phone = "+80000000005"
    state_machine = BotStateMachine()
    register_plugin("default Skill User", phone, state_machine, msg_timestamp=123)
    response = skills_plugin("default", phone, state_machine, msg_timestamp=123)
    assert "currently has skills" in response.lower()

def test_volunteer_find_command():
    """
    Tests a normal find scenario. Usually returns no volunteers if none match.
    """
    register_plugin = get_plugin("register")
    find_plugin = get_plugin("find")

    phone = "+80000000006"
    state_machine = BotStateMachine()
    register_plugin("default Find Me", phone, state_machine, msg_timestamp=123)
    response = find_plugin("default find", "+dummy", state_machine, msg_timestamp=123)
    assert isinstance(response, str)

def test_volunteer_add_skills_command():
    """
    Tests adding skills to an existing volunteer.
    """
    register_plugin = get_plugin("register")
    add_skills_plugin = get_plugin("add skills")

    phone = "+80000000007"
    state_machine = BotStateMachine()
    register_plugin("default Skill Adder", phone, state_machine, msg_timestamp=123)
    response = add_skills_plugin("default Python, Testing", phone, state_machine, msg_timestamp=123)
    assert any(keyword in response.lower() for keyword in ["registered", "updated"])

def test_volunteer_find_command_no_args_shows_usage():
    find_plugin = get_plugin("find")
    phone = "+80000000006"
    response = find_plugin("", phone, BotStateMachine(), msg_timestamp=123)
    assert "usage:" in response.lower()

def test_volunteer_add_skills_command_no_args_shows_usage():
    add_skills_plugin = get_plugin("add skills")
    phone = "+80000000007"
    response = add_skills_plugin("", phone, BotStateMachine(), msg_timestamp=123)
    assert "usage:" in response.lower()

def test_register_command_partial():
    """
    Tests that providing an incomplete name (only one word) for registration
    returns the flow's partial name message.
    """
    register_plugin = get_plugin("register")
    phone = "+80000000008"
    state_machine = BotStateMachine()
    response = register_plugin("default John", phone, state_machine, msg_timestamp=123)
    # Expect a prompt about first and last name
    assert "provide your first and last name" in response.lower()

def test_volunteer_delete_no_record():
    """
    If the user calls delete when they have no record, we expect 'nothing to delete' or similar.
    """
    delete_plugin = get_plugin("delete")
    phone = "+80000000010"
    state_machine = BotStateMachine()
    response = delete_plugin("default", phone, state_machine, msg_timestamp=123)
    assert "not currently registered" in response.lower() or "nothing to delete" in response.lower()

# End of tests/plugins/test_volunteer_commands.py