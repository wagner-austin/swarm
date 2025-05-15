#!/usr/bin/env python
"""
tests/core/test_database_volunteers.py - Tests for volunteer-related database operations.
Verifies functions to manage volunteer records including creation, update, and deletion.
(Adjusted to remove references to roles/skills in the volunteer manager interface.)
"""

from db.volunteers import (
    add_volunteer_record,
    get_volunteer_record,
    delete_volunteer_record,
)
from managers.volunteer_manager import register_volunteer

def test_volunteer_operations_add_and_update():
    """
    Tests adding and updating volunteer records using separate db.volunteers functions
    (not the manager).
    """
    phone = "+1234567890"
    add_volunteer_record(phone, "Test Volunteer", ["Skill1", "Skill2"], True, None)
    record = get_volunteer_record(phone)
    assert record is not None
    assert record["name"] == "Test Volunteer"

def test_volunteer_operations_delete():
    """
    Tests deleting a volunteer record using the db.volunteers module.
    """
    phone = "+1234567891"
    add_volunteer_record(phone, "Delete Volunteer", ["SkillDel"], True, None)
    delete_volunteer_record(phone)
    record = get_volunteer_record(phone)
    assert record is None

def test_register_volunteer_method_creation_and_update():
    """
    Tests the centralized register_volunteer method for creating a new volunteer and updating an existing one.
    (Skills and roles removed from the manager interface.)
    """
    phone = "+5550000000"
    # Create a new volunteer
    msg1 = register_volunteer(phone, "Initial Name", True)
    assert "New volunteer" in msg1, "Expected a message indicating a new volunteer was registered."

    record = get_volunteer_record(phone)
    assert record is not None
    assert record["name"] == "Initial Name"

    # Update the volunteer with new details.
    msg2 = register_volunteer(phone, "Updated Name", False)
    assert "updated" in msg2.lower(), "Expected a message indicating the volunteer was updated."

    record_updated = get_volunteer_record(phone)
    assert record_updated is not None
    assert record_updated["name"] == "Updated Name"
    assert record_updated["available"] is False

# End of tests/core/test_database_volunteers.py