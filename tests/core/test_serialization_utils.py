#!/usr/bin/env python
"""
tests/core/test_serialization_utils.py - Unit tests for serialization utilities.
Tests the serialize_list and deserialize_list functions from core/serialization_utils.py.
"""

from bot_core.serialization_utils import serialize_list, deserialize_list

def test_serialize_list_empty():
    assert serialize_list([]) == ""

def test_serialize_list_non_empty():
    items = ["a", "b", "c"]
    result = serialize_list(items)
    # Expect a comma-separated string without extra spaces.
    assert result == "a,b,c"

def test_deserialize_list_empty():
    assert deserialize_list("") == []

def test_deserialize_list_non_empty():
    serialized = "a,b,c"
    result = deserialize_list(serialized)
    assert result == ["a", "b", "c"]

def test_deserialize_list_with_spaces():
    serialized = "a, b, c"
    result = deserialize_list(serialized)
    assert result == ["a", "b", "c"]

def test_serialize_deserialize_cycle():
    items = ["item1", "item2", "item3"]
    serialized = serialize_list(items)
    deserialized = deserialize_list(serialized)
    assert deserialized == items

# End of tests/core/test_serialization_utils.py