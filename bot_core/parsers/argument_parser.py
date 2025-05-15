#!/usr/bin/env python
"""
parsers/argument_parser.py - Argument parsing utilities.
Provides common functions for splitting command arguments and parsing key-value pairs,
centralizing repetitive string splitting and validation logic.
"""

from bot_core.parsers.plugin_arg_parser import PluginArgError

def split_args(args: str, sep: str = None, maxsplit: int = -1) -> list:
    """
    Splits the argument string into tokens.
    
    Args:
        args (str): The raw argument string.
        sep (str, optional): The delimiter to use for splitting. Defaults to None (whitespace splitting).
        maxsplit (int, optional): Maximum number of splits. Defaults to -1 (no limit).
    
    Returns:
        list: List of tokens.
    """
    if sep is None:
        return args.strip().split(maxsplit=maxsplit)
    else:
        return [token.strip() for token in args.split(sep, maxsplit) if token.strip()]

def parse_key_value_args(args: str, pair_delimiter: str = ",", key_value_separator: str = ":") -> dict:
    """
    Parses a string into a dictionary by splitting using the pair delimiter and key-value separator.
    
    Args:
        args (str): The raw argument string.
        pair_delimiter (str, optional): Delimiter between key-value pairs. Defaults to ",".
        key_value_separator (str, optional): Separator between key and value. Defaults to ":".
    
    Returns:
        dict: Dictionary of parsed key-value pairs.
    
    Raises:
        ValueError: If a pair does not contain the key-value separator.
    """
    result = {}
    pairs = [pair.strip() for pair in args.split(pair_delimiter) if pair.strip()]
    for pair in pairs:
        if key_value_separator not in pair:
            raise ValueError(f"Argument '{pair}' is not a valid key{key_value_separator}value pair.")
        key, value = pair.split(key_value_separator, 1)
        result[key.strip().lower()] = value.strip()
    return result

def parse_plugin_arguments(args: str, mode: str = 'auto', sep: str = None, maxsplit: int = -1) -> dict:
    """
    parsers/argument_parser.py - Unified parser for plugin command arguments.
    Centralizes argument parsing to support both positional and key-value pair modes.

    Parameters:
        args (str): Raw argument string.
        mode (str): Parsing mode, one of 'auto', 'kv', or 'positional'.
            'auto': Automatically use key-value parsing if a colon is present, otherwise positional.
            'kv': Force key-value parsing.
            'positional': Force positional argument splitting.
        sep (str, optional): Delimiter to use for positional splitting. Defaults to None.
        maxsplit (int, optional): Maximum number of splits for positional mode. Defaults to -1.
    
    Returns:
        dict: A dictionary with two keys:
            'tokens': list of positional tokens (empty if key-value mode is used).
            'kv': dictionary of key-value pairs (empty if positional mode is used).
    
    Raises:
        PluginArgError: If key-value parsing fails.
    """
    result = {"tokens": [], "kv": {}}
    raw = args.strip()
    if not raw:
        return result
    if mode == 'kv' or (mode == 'auto' and ':' in raw):
        try:
            result["kv"] = parse_key_value_args(raw)
        except ValueError as e:
            raise PluginArgError(f"Argument parsing error: {e}")
    else:
        result["tokens"] = split_args(raw, sep=sep, maxsplit=maxsplit)
    return result

# End of parsers/argument_parser.py