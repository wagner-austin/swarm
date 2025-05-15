#!/usr/bin/env python
"""
parsers/envelope_parser.py - Provides envelope parsing utilities.
Extracts sender, body, timestamp, group info, reply identifiers, and message type.
"""

import re
from typing import Optional

# Regex patterns for envelope parsing (as strings)
SENDER_PATTERN: str = r'\s*from:\s*(?:["“]?.+?["”]?\s+)?(\+\d{1,15})'
BODY_PATTERN: str = r'Body:\s*(.+)'
TIMESTAMP_PATTERN: str = r'Timestamp:\s*(\d+)'
GROUP_INFO_PATTERN: str = r'Id:\s*([^\n]+)'
REPLY_PATTERN: str = r'Quote:.*?Id:\s*([^\n]+)'
MESSAGE_TIMESTAMP_PATTERN: str = r'Message timestamp:\s*(\d+)'

# Precompile regex patterns at module level for reuse
SENDER_REGEX = re.compile(SENDER_PATTERN, re.IGNORECASE)
BODY_REGEX = re.compile(BODY_PATTERN)
TIMESTAMP_REGEX = re.compile(TIMESTAMP_PATTERN)
GROUP_INFO_REGEX = re.compile(GROUP_INFO_PATTERN)
REPLY_REGEX = re.compile(REPLY_PATTERN, re.DOTALL)
MESSAGE_TIMESTAMP_REGEX = re.compile(MESSAGE_TIMESTAMP_PATTERN)

def sanitize_text(text: str) -> str:
    """
    Sanitize the input text by removing control characters and trimming whitespace.
    Allows only printable characters.
    """
    # Remove non-printable control characters.
    text = re.sub(r'[\x00-\x1F\x7F]', '', text)
    return text.strip()

def parse_sender(message: str) -> Optional[str]:
    """
    Extract and return the sender phone number from the message.
    """
    match = SENDER_REGEX.search(message)
    return sanitize_text(match.group(1)) if match else None

def parse_body(message: str) -> Optional[str]:
    """
    Extract and return the message body.
    """
    match = BODY_REGEX.search(message)
    return sanitize_text(match.group(1)) if match else None

def parse_timestamp(message: str) -> Optional[int]:
    """
    Extract and return the general message timestamp as an integer.
    """
    match = TIMESTAMP_REGEX.search(message)
    return int(match.group(1)) if match else None

def parse_group_info(message: str) -> Optional[str]:
    """
    Extract and return the group ID if available.
    """
    if "Group info:" in message:
        match = GROUP_INFO_REGEX.search(message)
        return sanitize_text(match.group(1)) if match else None
    return None

def parse_reply_id(message: str) -> Optional[str]:
    """
    Extract the reply message ID from a quoted message if present.
    
    Parameters:
        message (str): The full incoming message text.
    
    Returns:
        Optional[str]: The reply message ID if found, otherwise None.
    """
    match = REPLY_REGEX.search(message)
    return sanitize_text(match.group(1)) if match else None

def parse_message_timestamp(message: str) -> Optional[str]:
    """
    Extract the original command's message timestamp from the message if present.
    
    Parameters:
        message (str): The full incoming message text.
    
    Returns:
        Optional[str]: The message timestamp as a string if found, otherwise None.
    """
    match = MESSAGE_TIMESTAMP_REGEX.search(message)
    return sanitize_text(match.group(1)) if match else None

def parse_message_type(message: str) -> str:
    """
    Determine the message type from the incoming message text.
    
    Returns:
        "typing" if the message indicates a typing event.
        "receipt" if the message indicates a receipt event.
        "text" for standard text messages.
    """
    lower_message = message.lower()
    if "typing message" in lower_message:
        return "typing"
    elif "receipt message" in lower_message:
        return "receipt"
    return "text"

# End of parsers/envelope_parser.py