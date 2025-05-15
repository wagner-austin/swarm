#!/usr/bin/env python
"""
tests/core/test_signal_client.py --- Tests for signal client functionalities.
Verifies that send_message constructs CLI flags correctly and that process_incoming
handles corrupted messages, partial quoting, and invalid group IDs appropriately.
"""
import pytest
from core.signal_client import send_message, process_incoming
import core.signal_client as sc
from core.state import BotStateMachine
# Removed import of PENDING_ACTIONS.

@pytest.fixture
def dummy_async_run_signal_cli(monkeypatch):
    calls = []
    async def dummy_async_run(args, stdin_input=None):
        calls.append(args)
        return "dummy output"
    monkeypatch.setattr(sc, "async_run_signal_cli", dummy_async_run)
    return calls

@pytest.mark.asyncio
async def test_direct_reply_in_group_chat(dummy_async_run_signal_cli):
    calls = dummy_async_run_signal_cli
    await send_message(
        to_number="+111",
        message="Group message",
        group_id="dummyGroupBase64",
        reply_quote_author="+222",
        reply_quote_timestamp="123",
        reply_quote_message="original"
    )
    assert "-g" in calls[0]
    assert "--quote-author" in calls[0]

@pytest.mark.asyncio
async def test_indirect_reply_in_private_chat(dummy_async_run_signal_cli):
    calls = dummy_async_run_signal_cli
    await send_message(
        to_number="+111",
        message="Private message"
    )
    assert "-g" not in calls[0]
    assert "--quote-author" not in calls[0]

@pytest.mark.asyncio
async def test_process_incoming_corrupted_messages(monkeypatch):
    messages_list = [
        "Envelope\nTimestamp: 1234\nBody: Missing from line\n",
        "Envelope\nfrom: +1234567\nTimestamp: 2345\n",
        "Envelope\nfrom: +9999999999\nBody: valid body\nTimestamp: 3456\n"
    ]
    async def dummy_receive_messages(logger=None):
        nonlocal messages_list
        to_return = messages_list[:]
        messages_list.clear()
        return to_return
    monkeypatch.setattr(sc, "receive_messages", dummy_receive_messages)
    processed_count = await process_incoming(BotStateMachine())
    assert processed_count == 1

@pytest.mark.asyncio
async def test_send_message_partial_quoting(dummy_async_run_signal_cli):
    calls = dummy_async_run_signal_cli
    await send_message(
        to_number="+111",
        message="Test message with missing reply quoting fields",
        group_id="ValidGroup",
        reply_quote_author=None,
        reply_quote_timestamp="987654321",
        reply_quote_message="partial reply"
    )
    invoked_args = calls[0]
    assert "ValidGroup" in invoked_args
    assert "--quote-author" not in invoked_args
    assert "--quote-timestamp" not in invoked_args
    assert "--quote-message" not in invoked_args

@pytest.mark.asyncio
async def test_send_message_invalid_group_id_and_partial_quoting(dummy_async_run_signal_cli):
    calls = dummy_async_run_signal_cli
    await send_message(
        to_number="+111",
        message="Test message with invalid group",
        group_id="!!invalid_base64!!",
        reply_quote_author=None,
        reply_quote_timestamp="123456789",
        reply_quote_message="original message"
    )
    invoked_args = calls[0]
    assert "!!invalid_base64!!" in invoked_args
    assert "--quote-author" not in invoked_args
    assert "--quote-timestamp" not in invoked_args
    assert "--quote-message" not in invoked_args

@pytest.mark.asyncio
async def test_process_incoming_with_partial_quoting(monkeypatch):
    messages_list = [
        "Envelope\nfrom: +1234567890\nBody: @bot echo Partial quoting test\nTimestamp: 2000\n"
    ]
    async def dummy_receive_messages(logger=None):
        nonlocal messages_list
        to_return = messages_list[:]
        messages_list.clear()
        return to_return
    monkeypatch.setattr(sc, "receive_messages", dummy_receive_messages)
    async def dummy_async_run_signal_cli(args, stdin_input=None):
        return "dummy output"
    monkeypatch.setattr(sc, "async_run_signal_cli", dummy_async_run_signal_cli)
    from managers.message_manager import MessageManager
    original_process_message = MessageManager.process_message
    def dummy_process_message(self, parsed, sender, volunteer_manager, msg_timestamp=None):
        return "Processed message with partial quoting"
    monkeypatch.setattr(MessageManager, "process_message", dummy_process_message)
    processed_count = await process_incoming(BotStateMachine())
    assert processed_count == 1
    monkeypatch.setattr(MessageManager, "process_message", original_process_message)

@pytest.mark.asyncio
async def test_send_message_partial_quoting_with_missing_reply_fields(dummy_async_run_signal_cli):
    calls = dummy_async_run_signal_cli
    await send_message(
        to_number="+111",
        message="Test message with missing reply quoting fields",
        group_id="ValidGroup",
        reply_quote_author=None,
        reply_quote_timestamp="987654321",
        reply_quote_message="partial reply"
    )
    invoked_args = calls[0]
    assert "ValidGroup" in invoked_args
    assert "--quote-author" not in invoked_args
    assert "--quote-timestamp" not in invoked_args
    assert "--quote-message" not in invoked_args

# End of tests/core/test_signal_client.py