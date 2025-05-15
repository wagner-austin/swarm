"""
tests/parsers/test_envelope_parser.py - Tests for envelope parsing functionalities.
This module tests extraction of sender, body, timestamps, group info, and reply details from message envelopes.
"""

from parsers.envelope_parser import parse_sender, parse_body, parse_timestamp, parse_group_info, parse_reply_id, parse_message_timestamp

def test_parse_sender():
    message = "Envelope\nfrom: +1234567890\nBody: Hello"
    sender = parse_sender(message)
    assert sender == "+1234567890"

def test_parse_body():
    message = "Envelope\nBody: This is a test message"
    body = parse_body(message)
    assert "test message" in body

def test_parse_timestamp():
    message = "Envelope\nTimestamp: 987654321"
    ts = parse_timestamp(message)
    assert ts == 987654321

def test_parse_group_info():
    message = "Envelope\nGroup info: Id: TestGroup"
    group = parse_group_info(message)
    assert group == "TestGroup"

def test_parse_reply_id():
    message = "Envelope\nQuote: ...\nId: Reply123"
    reply_id = parse_reply_id(message)
    assert reply_id == "Reply123"

def test_parse_message_timestamp():
    message = "Envelope\nMessage timestamp: 555666777"
    msg_ts = parse_message_timestamp(message)
    assert msg_ts == "555666777"

# End of tests/parsers/test_envelope_parser.py
