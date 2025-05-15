#!/usr/bin/env python
"""
tests/core/test_dependency_injection.py - Tests for dependency injection.
Verifies that critical modules accept dependencies and use them instead of global instances.
(Adjusted to add a 'get_volunteer_record' method to DummyVolunteerManager.)
"""

import sqlite3
import logging
import pytest
from db.repository import BaseRepository
from core.signal_client import send_message
from managers.message.message_dispatcher import dispatch_message
from parsers.message_parser import ParsedMessage
from core.state import BotStateMachine

# -------------------
# Dummy Connection Provider Tests
# -------------------

# Create a persistent in-memory connection.
_persistent_conn = sqlite3.connect(":memory:")
_persistent_conn.row_factory = sqlite3.Row
_persistent_conn.execute("CREATE TABLE Dummy (id INTEGER PRIMARY KEY AUTOINCREMENT, value TEXT)")
_persistent_conn.commit()

class DummyConnectionWrapper:
    """
    DummyConnectionWrapper - Wraps a sqlite3.Connection to override the close() method.
    """
    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, attr):
        return getattr(self._conn, attr)

    def close(self):
        # Override close to do nothing.
        pass

def dummy_connection_provider():
    return DummyConnectionWrapper(_persistent_conn)

class DummyRepository(BaseRepository):
    def __init__(self, connection_provider):
        super().__init__("Dummy", primary_key="id", connection_provider=connection_provider)

def test_dummy_repository_crud():
    repo = DummyRepository(dummy_connection_provider)
    # Create a record
    rec_id = repo.create({"value": "test_value"})
    assert rec_id > 0
    # Retrieve the record
    record = repo.get_by_id(rec_id)
    assert record is not None
    assert record["value"] == "test_value"
    # Update the record
    repo.update(rec_id, {"value": "updated_value"})
    updated = repo.get_by_id(rec_id)
    assert updated["value"] == "updated_value"
    # List records with filter
    records = repo.list_all(filters={"value": "updated_value"})
    assert any(r["id"] == rec_id for r in records)
    # Delete the record
    repo.delete(rec_id)
    assert repo.get_by_id(rec_id) is None

# -------------------
# Dummy Logger for Dependency Injection Tests
# -------------------

class ListHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record.getMessage())

@pytest.fixture
def dummy_logger():
    logger = logging.getLogger("dummy_logger")
    logger.setLevel(logging.DEBUG)
    handler = ListHandler()
    logger.addHandler(handler)
    yield logger, handler
    logger.removeHandler(handler)

# -------------------
# Dummy Volunteer Manager for Testing dispatch_message
# -------------------

class DummyVolunteerManager:
    def delete_volunteer(self, sender: str) -> str:
        return "deleted"

    def sign_up(self, sender: str, name: str, skills: list) -> str:
        return "dummy response"

    # Added to avoid AttributeError in dispatch_message:
    def get_volunteer_record(self, phone: str):
        return None

# -------------------
# Test Logger Injection in send_message
# -------------------

@pytest.mark.asyncio
async def test_send_message_with_dummy_logger(monkeypatch, dummy_logger):
    logger, handler = dummy_logger

    async def dummy_async_run(args, stdin_input=None):
        return "dummy output"
    monkeypatch.setattr("core.signal_client.async_run_signal_cli", dummy_async_run)
    await send_message(
        to_number="+1111111111",
        message="Test message",
        logger=logger
    )
    # Check that our dummy logger captured an info log.
    found = any("Sent to +1111111111: Test message" in msg for msg in handler.records)
    assert found

# -------------------
# Test Logger Injection in dispatch_message
# -------------------

def test_dispatch_message_with_dummy_logger(monkeypatch, dummy_logger):
    logger, handler = dummy_logger
    # Create a dummy ParsedMessage with an unknown command.
    parsed = ParsedMessage(
        sender="+1234567890",
        body="@bot unknowncommand",
        timestamp=123,
        group_id=None,
        reply_to=None,
        message_timestamp=None,
        command="unknowncommand",
        args=""
    )
    state_machine = BotStateMachine()
    dummy_volunteer_manager = DummyVolunteerManager()
    monkeypatch.setattr("plugins.manager.get_all_plugins", lambda: {})
    response = dispatch_message(parsed, "+1234567890", state_machine,
                                volunteer_manager=dummy_volunteer_manager,
                                msg_timestamp=123, logger=logger)
    # Since no plugin is found, response should be empty.
    assert response == ""
    # Now, create a faulty plugin that raises an exception.
    def faulty_plugin(args, sender, state_machine, msg_timestamp=None):
        raise Exception("Test error")
    from plugins.manager import alias_mapping, plugin_registry
    alias_mapping["faulty"] = "faulty"
    plugin_registry["faulty"] = {"function": faulty_plugin, "aliases": ["faulty"], "help_visible": True}
    parsed.command = "faulty"
    response_error = dispatch_message(parsed, "+1234567890", state_machine,
                                      volunteer_manager=dummy_volunteer_manager,
                                      msg_timestamp=123, logger=logger)
    assert "internal error" in response_error.lower()
    # Check that the logger recorded an exception message.
    assert any("Error executing plugin for command" in msg for msg in handler.records)
    # Cleanup faulty plugin registration.
    alias_mapping.pop("faulty", None)
    plugin_registry.pop("faulty", None)

# -------------------
# Test Logger Injection in MessageManager.process_message
# -------------------

def test_message_manager_process_message(monkeypatch):
    """
    Test that MessageManager.process_message correctly dispatches the dummy command.
    Since the welcome message is sent separately, the direct process_message response should be "dummy response".
    """
    from managers.message_manager import MessageManager
    from plugins.manager import alias_mapping, plugin_registry
    # Register a dummy plugin for the "dummy" command.
    alias_mapping["dummy"] = "dummy"
    plugin_registry["dummy"] = {
         "function": lambda args, sender, state_machine, msg_timestamp=None: "dummy response",
         "aliases": ["dummy"],
         "help_visible": True,
         "required_role": "everyone"  # <= ADDED to avoid permission check failure
    }
    state_machine = BotStateMachine()
    message_manager = MessageManager(state_machine)
    parsed = ParsedMessage(
        sender="+1111111111",
        body="@bot dummy",
        timestamp=123,
        group_id=None,
        reply_to=None,
        message_timestamp=None,
        command="dummy",
        args=""
    )
    dummy_volunteer_manager = DummyVolunteerManager()
    response = message_manager.process_message(parsed, parsed.sender, dummy_volunteer_manager, msg_timestamp=123)
    expected_response = "dummy response"
    # Cleanup dummy plugin registration.
    alias_mapping.pop("dummy", None)
    plugin_registry.pop("dummy", None)
    assert response == expected_response

# End of tests/core/test_dependency_injection.py