"""
tests/parsers/test_message_parser.py - Tests for message parsing functionalities.
"""

from bot_core.parsers.message_parser import parse_message

import pytest
@pytest.mark.asyncio
async def test_message_parsing():
    class Author:
        id = 42
    class Channel:
        id = 99
    class MockMessage:
        def __init__(self, content):
            self.content = content
            self.author = Author()
            self.channel = Channel()
            self.attachments = []

    msg = MockMessage("help arg1 arg2")
    parsed = parse_message(msg)
    assert parsed.content == "help arg1 arg2"
    assert parsed.author_id == 42
    assert parsed.channel_id == 99
    assert parsed.attachments == []
    assert parsed.command == "help"
    assert parsed.args == "arg1 arg2"

# End of tests/parsers/test_message_parser.py