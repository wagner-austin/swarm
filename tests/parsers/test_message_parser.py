"""
tests/parsers/test_message_parser.py - Tests for message parsing functionalities.
"""

from bot_core.parsers.message_parser import parse_message

def test_message_parsing():
    sample_message = (
        "Envelope\n"
        "from: +1234567890\n"
        "Body: @bot test\n"
        "Timestamp: 123456789\n"
        "Group info: Id: SomeGroup\n"
        "Message timestamp: 123456789\n"
    )
    parsed = parse_message(sample_message)
    assert parsed.sender == "+1234567890"
    assert parsed.body.startswith("@bot")

# End of tests/parsers/test_message_parser.py