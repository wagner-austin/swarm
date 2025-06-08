"""
tests/parsers/test_message_parser.py - Tests for message parsing functionalities.
"""

from typing import Any
from bot.core.parsers import parse_message

import pytest


@pytest.mark.asyncio
async def test_message_parsing() -> None:
    class Author:
        id = 42

    class Channel:
        id = 99

    class MockMessage:
        def __init__(self, content: str) -> None:
            self.content = content
            self.author = Author()
            self.channel = Channel()
            self.attachments: list[Any] = []

    msg = MockMessage("help arg1 arg2")
    parsed = parse_message(msg)
    assert parsed.content == "help arg1 arg2"
    assert parsed.author_id == 42
    assert parsed.channel_id == 99
    assert parsed.attachments == []
    assert parsed.command == "help"
    assert parsed.args == "arg1 arg2"
