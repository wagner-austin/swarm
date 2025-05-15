"""
parsers/command_extractor.py
----------------------------
Extract commands and arguments from a message. Supports multi-word commands by matching
against registered aliases and considering group vs. private chat prefix rules.
"""

import re
from typing import Optional, Tuple
from plugins.manager import alias_mapping  # Import the alias mapping

def _validate_command(command: str) -> bool:
    """
    Validate that the command consists only of allowed characters:
    lowercase letters, digits, and spaces.
    """
    return re.match(r'^[a-z0-9 ]+$', command) is not None

def _parse_default_command(message: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Parse command and arguments from a message using registered aliases.

    Args:
        message (str): The normalized message string.

    Returns:
        Tuple[Optional[str], Optional[str]]: The canonical command and its arguments.
    """
    message_lower = message.lower()
    # Get all aliases sorted by descending length to match longer phrases first.
    aliases = sorted(alias_mapping.keys(), key=lambda x: len(x), reverse=True)
    for alias in aliases:
        if message_lower.startswith(alias) and (
            len(message_lower) == len(alias) or message_lower[len(alias)] == " "
        ):
            args = message[len(alias):].strip()
            # Map alias to canonical command.
            canonical = alias_mapping[alias]
            return canonical, args
    # Fallback: split by the first space.
    parts = message.split(" ", 1)
    command = parts[0].strip().lower()
    if not _validate_command(command):
        return None, None
    args = parts[1].strip() if len(parts) == 2 else ""
    return command, args

def parse_command_from_body(body: Optional[str], is_group: bool = False) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract the command and its arguments from the message body, taking into account
    whether the message is from a group chat or a private chat.

    In group chats (is_group=True), the message must start with one of these prefixes:
      - "@bot"
      - "@50501oc bot"
      - "bot"
    If no prefix is found, returns (None, None).

    In private chats (is_group=False), the prefix is optional. If present, it will be
    stripped. Otherwise, the entire message is treated as the command.

    If the message begins with the object replacement character (U+FFFC),
    it is replaced with "@50501oc bot".

    Args:
        body (Optional[str]): The text body of the message.
        is_group (bool): True if the message is from a group chat, False if private.

    Returns:
        Tuple[Optional[str], Optional[str]]: The canonical command and arguments,
        or (None, None) if parsing fails or no valid prefix is detected (group only).
    """
    if not body:
        return None, None

    # Normalize whitespace.
    message = " ".join(body.strip().split())

    # Replace object replacement character if present.
    if message and message[0] == "\uFFFC":
        message = "@50501oc bot" + message[1:]
        message = message.strip()

    allowed_prefixes = ["@bot", "@50501oc bot", "bot"]

    def _find_prefix(text: str) -> Optional[str]:
        """
        Return the matched prefix if the text starts with one, else None.
        """
        lower_text = text.lower()
        for pfx in allowed_prefixes:
            if lower_text.startswith(pfx):
                return pfx
        return None

    if is_group:
        # Require a prefix
        matched_prefix = _find_prefix(message)
        if not matched_prefix:
            return None, None
        # Strip the prefix and parse the remainder
        message = message[len(matched_prefix):].strip()
        return _parse_default_command(message)
    else:
        # Optional prefix in private chat
        matched_prefix = _find_prefix(message)
        if matched_prefix:
            message = message[len(matched_prefix):].strip()
        return _parse_default_command(message)

# End of parsers/command_extractor.py