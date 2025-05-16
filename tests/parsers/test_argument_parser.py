#!/usr/bin/env python
"""
tests/parsers/test_argument_parser.py - Tests for argument parsing utilities.
Verifies that split_args and parse_key_value_args work as expected.
"""

import pytest
from bot_core.parsers import split_args, parse_key_value_args


@pytest.mark.asyncio
async def test_split_args_default() -> None:
    # When no delimiter is provided, split on whitespace.
    text = "this is a test"
    result = split_args(text)
    assert result == ["this", "is", "a", "test"]


@pytest.mark.asyncio
async def test_split_args_custom_delimiter() -> None:
    # Test with a custom delimiter.
    text = "key1:value1;key2:value2;key3:value3"
    result = split_args(text, sep=";")
    assert result == ["key1:value1", "key2:value2", "key3:value3"]


@pytest.mark.asyncio
async def test_split_args_maxsplit() -> None:
    text = "a b c d e"
    result = split_args(text, maxsplit=2)
    assert result == ["a", "b", "c d e"]


@pytest.mark.asyncio
async def test_parse_key_value_args_valid() -> None:
    text = "key1: value1, key2: value2, key3: value3"
    result = parse_key_value_args(text)
    expected = {"key1": "value1", "key2": "value2", "key3": "value3"}
    assert result == expected


@pytest.mark.asyncio
async def test_parse_key_value_args_custom_delimiters() -> None:
    text = "a=1; b=2; c=3"
    # Use ';' as pair_delimiter and '=' as key_value_separator
    result = parse_key_value_args(text, pair_delimiter=";", key_value_separator="=")
    expected = {"a": "1", "b": "2", "c": "3"}
    assert result == expected


@pytest.mark.asyncio
async def test_parse_key_value_args_invalid_pair() -> None:
    text = "key1: value1, invalidpair, key2: value2"
    with pytest.raises(ValueError) as excinfo:
        parse_key_value_args(text)
    assert "is not a valid key:value pair" in str(excinfo.value)
