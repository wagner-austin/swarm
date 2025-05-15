#!/usr/bin/env python
"""
tests/core/test_messages.py - Tests for core/messages constants.
Verifies that key message constants are defined, non-empty, and match updated text.
(Removed older checks for 'register' or injecting the user's name.)
"""

import plugins.messages as messages

def test_already_registered():
    formatted = messages.ALREADY_REGISTERED_WITH_INSTRUCTIONS.format(name="Test")
    assert isinstance(formatted, str) and formatted, "ALREADY_REGISTERED_WITH_INSTRUCTIONS must be non-empty."
    assert "Test" in formatted, "Formatted string must include the provided name."

def test_edit_prompt():
    formatted = messages.EDIT_PROMPT
    assert isinstance(formatted, str) and formatted, "EDIT_PROMPT must be a non-empty string."
    # Removed the check for {name}, as the prompt no longer inserts it.

def test_deletion_prompts():
    assert isinstance(messages.DELETION_PROMPT, str) and messages.DELETION_PROMPT, "DELETION_PROMPT must be non-empty."
    assert isinstance(messages.DELETION_CANCELED, str) and messages.DELETION_CANCELED, "DELETION_CANCELED must be non-empty."

def test_new_volunteer_registered():
    formatted = messages.NEW_VOLUNTEER_REGISTERED.format(name="Test")
    assert isinstance(formatted, str) and formatted, "NEW_VOLUNTEER_REGISTERED must be a non-empty string."
    assert "Test" in formatted, "NEW_VOLUNTEER_REGISTERED formatted string must include the provided name."

def test_registration_welcome():
    """
    Confirm the welcome message is defined and not empty, but no longer requires 'register' substring.
    """
    assert isinstance(messages.REGISTRATION_WELCOME, str) and messages.REGISTRATION_WELCOME, \
        "REGISTRATION_WELCOME must be a non-empty string."

def test_deletion_confirm():
    assert isinstance(messages.DELETION_CONFIRM, str) and messages.DELETION_CONFIRM, "DELETION_CONFIRM must be non-empty."

def test_getting_started():
    assert isinstance(messages.GETTING_STARTED, str) and messages.GETTING_STARTED, "GETTING_STARTED must be non-empty."
    assert "help" in messages.GETTING_STARTED.lower(), "GETTING_STARTED should contain 'help'."

# End of tests/core/test_messages.py