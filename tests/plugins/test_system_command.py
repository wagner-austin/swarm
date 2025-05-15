"""
File: tests/plugins/test_system_command.py
-----------------------------------------
Deeper coverage tests for system plugin commands.
Verifies 'shutdown' transitions the BotStateMachine and 'assign <skill>' picks the correct volunteer or none.
"""

from core.state import BotStateMachine, BotState
from managers.volunteer_manager import VOLUNTEER_MANAGER
from db.volunteers import get_volunteer_record
from plugins.manager import get_plugin

def test_shutdown_command_integration():
    """
    Test that calling the shutdown command transitions the BotStateMachine to SHUTTING_DOWN.
    """
    state_machine = BotStateMachine()
    sender = "+9999999999"
    shutdown_plugin = get_plugin("shutdown")
    response = shutdown_plugin("", sender, state_machine, msg_timestamp=123)
    assert "bot is shutting down" in response.lower()
    assert state_machine.current_state == BotState.SHUTTING_DOWN

def test_assign_command_with_multiple_matches():
    """
    Test that when multiple volunteers have the requested skill, the 'assign <skill>' command
    assigns the first matching volunteer. The volunteer's current_role becomes the skill name.
    """
    phone1 = "+9000000001"
    phone2 = "+9000000002"

    # Create two volunteers with the same skill, both available, and no current_role.
    VOLUNTEER_MANAGER.register_volunteer(phone1, "First Volunteer", ["Photography"], True, None)
    VOLUNTEER_MANAGER.register_volunteer(phone2, "Second Volunteer", ["Photography"], True, None)

    assign_plugin = get_plugin("assign")
    state_machine = BotStateMachine()

    response = assign_plugin("default Photography", "+dummy", state_machine, msg_timestamp=123)
    # Confirm it assigned the first volunteer created (phone1).
    assert response == "Photography assigned to First Volunteer."

    record1 = get_volunteer_record(phone1)
    record2 = get_volunteer_record(phone2)
    assert record1 is not None
    assert record1["current_role"] == "Photography", "First Volunteer should be assigned the skill role."
    assert record2 is not None
    assert record2["current_role"] is None, "Second Volunteer should remain unassigned."

def test_assign_command_no_matches():
    """
    Test that 'assign <skill>' returns an appropriate message if no volunteers match the skill
    or availability requirements.
    """
    assign_plugin = get_plugin("assign")
    state_machine = BotStateMachine()
    response = assign_plugin("default UnknownSkill", "+dummy", state_machine, msg_timestamp=123)
    assert response == "No available volunteer for UnknownSkill."

# End of tests/plugins/test_system_command.py