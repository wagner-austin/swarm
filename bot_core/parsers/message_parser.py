#!/usr/bin/env python
"""
parsers/message_parser.py - Combines envelope parsing with command extraction.
Produces a structured ParsedMessage dataclass with fields for sender, body, timestamp, group info,
reply identifier, message timestamp, and message type.
"""

from typing import Any
from dataclasses import dataclass

from typing import Optional
from dataclasses import dataclass

@dataclass
class ParsedMessage:
    content: str
    author_id: int
    channel_id: int
    attachments: list
    command: Optional[str] = None
    args: str = ""

def parse_message(message: Any) -> ParsedMessage:
    """
    Extracts relevant fields from a discord.Message object and minimally splits for command/args.

    Args:
        message (discord.Message): The Discord message object.

    Returns:
        ParsedMessage: An object containing content, author_id, channel_id, attachments, command, and args.
    """
    content = message.content.strip()
    if not content:
        cmd = None
        argstr = ""
    else:
        parts = content.split(maxsplit=1)
        cmd = parts[0].lower()
        argstr = parts[1] if len(parts) == 2 else ""
    return ParsedMessage(
        content=message.content,
        author_id=message.author.id,
        channel_id=message.channel.id,
        attachments=list(message.attachments),
        command=cmd,
        args=argstr
    )

# End of parsers/message_parser.py