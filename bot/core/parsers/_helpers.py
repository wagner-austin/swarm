from typing import Any, Optional
from dataclasses import dataclass


@dataclass
class ParsedMessage:
    content: str
    author_id: int
    channel_id: int
    attachments: list[Any]
    command: str
    args: str


# Helper to split arguments


def split_args(
    text: str, *, sep: Optional[str] = None, maxsplit: int = -1
) -> list[str]:
    return text.split(sep, maxsplit)


# Helper to parse key-value arguments


def parse_key_value_args(
    text: str, *, pair_delimiter: str = ",", key_value_separator: str = ":"
) -> dict[str, str]:
    """
    Parse a string of key-value pairs into a dictionary.

    Args:
        text: The input string containing key-value pairs.
        pair_delimiter: The delimiter between pairs (default: ',').
        key_value_separator: The separator between key and value (default: ':').

    Returns:
        A dictionary mapping keys to values.

    Raises:
        ValueError: If any pair does not contain the key_value_separator.

    Example:
        parse_key_value_args('a:1, b:2') -> {'a': '1', 'b': '2'}
        parse_key_value_args('a=1; b=2', pair_delimiter=';', key_value_separator='=') -> {'a': '1', 'b': '2'}
        parse_key_value_args('invalidpair, a:1')  # raises ValueError
    """
    result = {}
    pairs = text.split(pair_delimiter)
    for pair in pairs:
        if key_value_separator not in pair:
            raise ValueError(
                f"'{pair.strip()}' is not a valid key{key_value_separator}value pair"
            )
        key, value = pair.split(key_value_separator, 1)
        result[key.strip()] = value.strip()
    return result


# Helper to parse a message object


def parse_message(msg: Any) -> ParsedMessage:
    content = getattr(msg, "content", "")
    author_id = getattr(getattr(msg, "author", None), "id", None)
    channel_id = getattr(getattr(msg, "channel", None), "id", None)
    attachments = getattr(msg, "attachments", [])
    # Assume command is first word, args is the rest
    parts = content.strip().split(maxsplit=1)
    command = parts[0] if parts else ""
    args = parts[1] if len(parts) > 1 else ""
    return ParsedMessage(
        content=content,
        author_id=int(author_id) if author_id is not None else 0,
        channel_id=int(channel_id) if channel_id is not None else 0,
        attachments=attachments,
        command=command,
        args=args,
    )
