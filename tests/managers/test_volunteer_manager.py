#!/usr/bin/env python
"""
tests/managers/test_volunteer_manager.py - Tests for aggregated volunteer management functionalities
----------------------------------------------------------------------------------------------------
Verifies that operations like register_volunteer, check_in, deletion, status retrieval, and role
management work correctly. Also covers the normalize_name function plus any edge-case flows such
as invalid phone formats, concurrency tests, and logging checks for deletions.
"""

import pytest
import logging
import concurrent.futures
from core.exceptions import VolunteerError
from db.volunteers import get_volunteer_record
from managers.volunteer_manager import (
    VOLUNTEER_MANAGER,
    register_volunteer,
    delete_volunteer,
    check_in,
    normalize_name
)


# -----------------------------------------------------------------------------
# Existing tests from test_volunteer_manager.py
# -----------------------------------------------------------------------------
@pytest.mark.parametrize(
    "phone, name, skills, expected_substring",
    [
        ("+10000000001", "John Doe", ["Public Speaking"], "John Doe"),
        ("+10000000002", "Jane Smith", ["Greeter"], "Jane Smith"),
        ("+10000000003", "Alice Johnson", ["Logistics Oversight"], "Alice Johnson"),
    ]
)
def test_register_volunteer_and_status(phone, name, skills, expected_substring):
    """
    Test registering volunteers and verifying their status.
    Uses parametrization for different phone/name/skills combos.
    """
    result = VOLUNTEER_MANAGER.register_volunteer(phone, name, skills)
    assert "registered" in result.lower() or "updated" in result.lower()
    status = VOLUNTEER_MANAGER.volunteer_status()
    assert expected_substring in status


@pytest.mark.parametrize(
    "phone, name, skills",
    [
        ("+10000000002", "Jane Smith", ["Greeter"]),
        ("+10000000008", "Tom Tester", ["AnySkill"]),
    ]
)
def test_check_in(phone, name, skills):
    """
    Test checking in a volunteer with multiple scenarios.
    """
    VOLUNTEER_MANAGER.register_volunteer(phone, name, skills)
    result = VOLUNTEER_MANAGER.check_in(phone)
    assert "checked in" in result.lower()


@pytest.mark.parametrize(
    "phone, name, skills",
    [
        ("+10000000003", "Alice Johnson", ["Logistics Oversight"]),
        ("+10000000009", "Another Person", ["SomeSkill"]),
    ]
)
def test_delete_volunteer_original(phone, name, skills):
    """
    Test deleting volunteers using parametrization for multiple phone/name combos.
    (Original test_delete_volunteer from test_volunteer_manager.py)
    """
    VOLUNTEER_MANAGER.register_volunteer(phone, name, skills)
    result = VOLUNTEER_MANAGER.delete_volunteer(phone)
    assert "deleted" in result.lower()
    record = get_volunteer_record(phone)
    assert record is None


@pytest.mark.parametrize(
    "phone, name, skills, is_available, role",
    [
        ("+10000000004", "Test Volunteer", ["SkillX"], False, "Tester"),
        ("+10000000010", "Another Volunteer", ["SkillA", "SkillB"], True, "Coordinator"),
    ]
)
def test_register_volunteer_with_availability_and_role(phone, name, skills, is_available, role):
    """
    Tests that register_volunteer correctly handles availability and role for different volunteers.
    """
    # Create a new volunteer with the specified availability and role
    result_create = VOLUNTEER_MANAGER.register_volunteer(phone, name, skills, is_available, role)
    assert "registered" in result_create.lower()

    record = get_volunteer_record(phone)
    assert record is not None
    assert record["name"] == name
    for skl in skills:
        assert skl in record["skills"]
    assert record["available"] == is_available
    assert record["current_role"] == role

    # Update the volunteer with an additional skill
    new_skill = ["ExtraSkill"]
    result_update = VOLUNTEER_MANAGER.register_volunteer(phone, name + " Updated", new_skill, not is_available, role)
    assert "updated" in result_update.lower()

    updated_record = get_volunteer_record(phone)
    assert updated_record is not None
    assert updated_record["name"] == name + " Updated"
    for skl in (skills + new_skill):
        assert skl in updated_record["skills"]
    assert updated_record["available"] == (not is_available)
    assert updated_record["current_role"] == role


def test_concurrent_register_volunteer_same_user():
    """
    Test concurrent register_volunteer calls using the same phone number,
    with different names and skills. Verifies that the final record merges
    all skills (union) and ends with whichever name was last, ensuring no
    partial merges or errors under concurrency.
    """
    phone = "+10000000042"

    # If volunteer exists, remove them
    existing = get_volunteer_record(phone)
    if existing:
        VOLUNTEER_MANAGER.delete_volunteer(phone)

    concurrency_data = [
        ("ConcurrentOne", ["SkillA"]),
        ("ConcurrentTwo", ["SkillB", "SkillC"]),
        ("ConcurrentThree", ["SkillB", "SkillX"]),
        ("ConcurrentFour", ["SkillA", "SkillD"]),
        ("ConcurrentFive", ["SkillZ"]),
    ]

    def register_task(name, these_skills):
        return VOLUNTEER_MANAGER.register_volunteer(phone, name, these_skills, True, None)

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(concurrency_data)) as executor:
        futures = [
            executor.submit(register_task, name, sk) for (name, sk) in concurrency_data
        ]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    for res in results:
        assert any(word in res.lower() for word in ["registered", "updated", "volunteer"])

    final_record = get_volunteer_record(phone)
    assert final_record is not None

    possible_names = {cd[0] for cd in concurrency_data}
    assert final_record["name"] in possible_names

    merged_skills = set()
    for _, skill_list in concurrency_data:
        merged_skills.update(skill_list)
    for skl in merged_skills:
        assert skl in final_record["skills"]


def test_list_volunteers_method():
    """
    Test that VOLUNTEER_MANAGER.list_all_volunteers() returns a dictionary
    mapping phone numbers to volunteer data.
    """
    phone = "+7777777777"
    result = VOLUNTEER_MANAGER.register_volunteer(phone, "List Test Volunteer", ["SkillX"], True, None)
    assert "registered" in result.lower() or "updated" in result.lower()
    volunteers = VOLUNTEER_MANAGER.list_all_volunteers()
    assert phone in volunteers
    assert volunteers[phone]["name"] == "List Test Volunteer"


# -----------------------------------------------------------------------------
# Merged tests from test_volunteer_common.py (normalize_name coverage)
# -----------------------------------------------------------------------------
def test_normalize_name_same_as_fallback():
    """
    If the name is exactly the same as the fallback phone, return "Anonymous".
    """
    phone = "+5555555555"
    assert normalize_name(phone, phone) == "Anonymous"


def test_normalize_name_phone_pattern():
    """
    If the provided name looks like a phone number, return "Anonymous".
    """
    fallback = "+1234567890"
    assert normalize_name("+5555555555", fallback) == "Anonymous"


def test_normalize_name_valid_name():
    """
    If the name is a normal non-phone string, keep it.
    """
    phone = "+5555555555"
    name = "John Doe"
    assert normalize_name(name, phone) == "John Doe"


# -----------------------------------------------------------------------------
# Merged tests from test_volunteer_operations.py
# (Extra checks for register/delete/check_in & edge cases)
# -----------------------------------------------------------------------------
@pytest.mark.parametrize(
    "phone, name, skills, available, current_role",
    [
        ("+40000000001", "Test Volunteer Ops A", ["Skill1"], True, "Tester"),
        ("+40000000002", "Test Volunteer Ops B", ["Skill2", "Skill3"], False, None),
    ]
)
def test_vol_ops_register_creates_volunteer(phone, name, skills, available, current_role):
    """
    Additional coverage for register_volunteer with explicit parameters.
    """
    record = get_volunteer_record(phone)
    if record:
        delete_volunteer(phone)

    msg = register_volunteer(phone, name, skills, available, current_role)
    assert "registered" in msg.lower()

    new_rec = get_volunteer_record(phone)
    assert new_rec is not None
    assert new_rec["name"] == name
    for s in skills:
        assert s in new_rec["skills"]
    assert new_rec["available"] == available
    assert new_rec["role"] == current_role  # stored in 'role', same as 'current_role'


@pytest.mark.parametrize(
    "phone, name, skills",
    [
        ("+40000000010", "To Be Deleted1", ["SkillDel"]),
        ("+40000000011", "To Be Deleted2", ["SkillX", "SkillY"]),
    ]
)
def test_vol_ops_delete_volunteer_caplog(phone, name, skills, caplog):
    """
    Ensures that deleting volunteers logs an info message.
    """
    register_volunteer(phone, name, skills)
    with caplog.at_level(logging.INFO):
        msg = delete_volunteer(phone)
    assert "deleted" in msg.lower()
    record = get_volunteer_record(phone)
    assert record is None
    assert any("deleted from the system" in rec.message for rec in caplog.records)


@pytest.mark.parametrize(
    "phone, name, skills",
    [
        ("+40000000003", "CheckIn Volunteer A", ["SkillCheck"]),
        ("+40000000004", "CheckIn Volunteer B", ["SkillA"]),
    ]
)
def test_vol_ops_check_in(phone, name, skills):
    """
    Confirm check_in sets volunteer to available = True.
    """
    register_volunteer(phone, name, skills, False, None)
    msg = check_in(phone)
    assert "checked in" in msg.lower()
    record = get_volunteer_record(phone)
    assert record["available"] is True


@pytest.mark.parametrize(
    "phone, name, skills",
    [
        ("+40000000005", "EmptyRole A", ["SkillA"]),
        ("+40000000006", "EmptyRole B", ["SkillB", "SkillC"]),
    ]
)
def test_vol_ops_register_with_empty_role(phone, name, skills):
    """
    If a user provides an empty string as role, it remains None or 'registered' internally.
    """
    msg = register_volunteer(phone, name, skills, True, "")
    assert "registered" in msg.lower()
    record = get_volunteer_record(phone)
    assert record is not None
    # 'role' column might store 'registered' or None internally, depending on logic
    # We'll check that "current_role" is None for the domain logic.
    assert record.get("role") in (None, "registered")


@pytest.mark.parametrize(
    "invalid_phone",
    [
        "",               # empty
        "abc",            # not numeric
        "+1 234567",      # space in middle
        "+1234567890123456",  # 16 digits (beyond 15 max)
        "123456",         # 6 digits (less than 7 required)
    ]
)
def test_vol_ops_register_invalid_phone(invalid_phone):
    """
    Test that register_volunteer raises VolunteerError if phone is invalid.
    """
    name = "Invalid Phone"
    skills = ["SkillX"]
    with pytest.raises(VolunteerError, match="Invalid phone number format"):
        register_volunteer(invalid_phone, name, skills, True, None)


@pytest.mark.parametrize(
    "phone",
    [
        "+40000000007",
        "+40000000008",
    ]
)
def test_vol_ops_delete_unregistered_volunteer(phone):
    """
    Attempting to delete an unregistered volunteer should raise VolunteerError.
    """
    with pytest.raises(VolunteerError, match="not registered"):
        delete_volunteer(phone)

# End of tests/managers/test_volunteer_manager.py