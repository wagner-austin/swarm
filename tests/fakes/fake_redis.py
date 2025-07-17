"""
Fake Redis Client for Testing
==============================

Provides a fake implementation of Redis operations that doesn't require
actual Redis infrastructure, enabling fast and reliable unit tests.
"""

import asyncio
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set


class FakeRedisClient:
    """
    Fake Redis client that simulates Redis operations in-memory
    without requiring actual Redis infrastructure.
    """

    def __init__(
        self, should_fail: bool = False, fail_message: str = "Simulated Redis failure"
    ) -> None:
        self.should_fail = should_fail
        self.fail_message = fail_message
        self.data: dict[str, Any] = {}
        self.hashes: dict[str, dict[bytes, bytes]] = defaultdict(dict)
        self.sets: dict[str, set[bytes]] = defaultdict(set)
        self.streams: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.stream_groups: dict[str, set[str]] = defaultdict(set)
        self.lists: dict[str, list[str]] = defaultdict(list)
        self.expiry: dict[str, float] = {}
        self.call_history: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def _record_call(self, method_name: str, *args: Any, **kwargs: Any) -> None:
        """Record method calls for test verification."""
        self.call_history.append((method_name, args, kwargs))

    def _check_expiry(self, key: str) -> bool:
        """Check if a key has expired."""
        if key in self.expiry:
            if time.time() > self.expiry[key]:
                self._delete_key(key)
                return True
        return False

    def _delete_key(self, key: str) -> None:
        """Delete a key from all data structures."""
        self.data.pop(key, None)
        self.hashes.pop(key, None)
        self.sets.pop(key, None)
        self.streams.pop(key, None)
        self.lists.pop(key, None)
        self.expiry.pop(key, None)

    async def keys(self, pattern: str = "*") -> list[bytes]:
        """Simulate Redis KEYS command with pattern matching."""
        self._record_call("keys", pattern)
        if self.should_fail:
            raise ConnectionError(self.fail_message)

        await asyncio.sleep(0.001)  # Simulate async operation

        # Simple pattern matching (only supports * wildcard)
        if pattern == "*":
            all_keys = list(self.data.keys()) + list(self.hashes.keys()) + list(self.sets.keys())
        else:
            import fnmatch

            all_keys = []
            for storage in [self.data, self.hashes, self.sets]:
                for key in storage.keys():
                    if fnmatch.fnmatch(key, pattern):
                        all_keys.append(key)

        # Filter out expired keys and convert to bytes
        result = []
        for key in all_keys:
            if not self._check_expiry(key):
                result.append(key.encode() if isinstance(key, str) else key)

        return result

    async def scan(self, cursor: int, match: str = "*", count: int = 10) -> tuple[int, list[str]]:
        """Simulate Redis SCAN command."""
        self._record_call("scan", cursor, match=match, count=count)
        if self.should_fail:
            raise ConnectionError(self.fail_message)

        await asyncio.sleep(0.001)

        # Get all keys
        all_keys: list[str] = []
        for storage in [self.data, self.hashes, self.sets, self.streams]:
            all_keys.extend(storage.keys())

        # Apply pattern matching
        if match != "*":
            import fnmatch

            matching_keys = [k for k in all_keys if fnmatch.fnmatch(k, match)]
        else:
            matching_keys = all_keys

        # Filter out expired keys
        valid_keys = [k for k in matching_keys if not self._check_expiry(k)]

        # For simplicity, always return cursor 0 (no more keys)
        return (0, valid_keys)

    async def hget(self, name: str, key: str) -> bytes | None:
        """Simulate Redis HGET command."""
        self._record_call("hget", name, key)
        if self.should_fail:
            raise ConnectionError(self.fail_message)

        await asyncio.sleep(0.001)

        if self._check_expiry(name):
            return None

        key_bytes = key.encode() if isinstance(key, str) else key
        return self.hashes.get(name, {}).get(key_bytes)

    async def hset(
        self, name: str, key: str, value: str | bytes, mapping: dict[Any, Any] | None = None
    ) -> int:
        """Simulate Redis HSET command."""
        self._record_call("hset", name, key, value, mapping=mapping)
        if self.should_fail:
            raise ConnectionError(self.fail_message)

        await asyncio.sleep(0.001)

        if mapping:
            # Handle mapping case
            for k, v in mapping.items():
                k_bytes = k.encode() if isinstance(k, str) else k
                v_bytes = v.encode() if isinstance(v, str) else v
                self.hashes[name][k_bytes] = v_bytes
            return len(mapping)
        else:
            # Handle single key-value case
            key_bytes = key.encode() if isinstance(key, str) else key
            value_bytes = value.encode() if isinstance(value, str) else value
            is_new = key_bytes not in self.hashes.get(name, {})
            self.hashes[name][key_bytes] = value_bytes
            return 1 if is_new else 0

    async def hgetall(self, name: str) -> dict[bytes, bytes]:
        """Simulate Redis HGETALL command."""
        self._record_call("hgetall", name)
        if self.should_fail:
            raise ConnectionError(self.fail_message)

        await asyncio.sleep(0.001)

        if self._check_expiry(name):
            return {}

        return dict(self.hashes.get(name, {}))

    async def expire(self, name: str, seconds: int) -> bool:
        """Simulate Redis EXPIRE command."""
        self._record_call("expire", name, seconds)
        if self.should_fail:
            raise ConnectionError(self.fail_message)

        await asyncio.sleep(0.001)

        # Check if key exists in any storage
        exists = name in self.data or name in self.hashes or name in self.sets
        if exists:
            self.expiry[name] = time.time() + seconds
            return True
        return False

    async def xgroup_create(
        self, stream: str, group: str, id: str = "$", mkstream: bool = False
    ) -> None:
        """Simulate Redis XGROUP CREATE command."""
        self._record_call("xgroup_create", stream, group, id, mkstream=mkstream)
        if self.should_fail:
            raise ConnectionError(self.fail_message)

        # Add the group to stream_groups
        self.stream_groups[stream].add(group)

        await asyncio.sleep(0.001)

        # Simulate consumer group creation
        if stream not in self.streams and not mkstream:
            raise Exception("ERR no such key")

        if stream not in self.streams:
            self.streams[stream] = []

    async def xadd(
        self, stream: str, fields: dict[str, Any], id: str = "*", maxlen: int | None = None
    ) -> str:
        """Simulate Redis XADD command."""
        self._record_call("xadd", stream, fields, id=id)
        if self.should_fail:
            raise ConnectionError(self.fail_message)

        await asyncio.sleep(0.001)

        # Generate ID if not specified
        if id == "*":
            id = f"{int(time.time() * 1000)}-0"

        self.streams[stream].append({"id": id, "fields": fields})

        # Trim stream if maxlen is specified
        if maxlen is not None and len(self.streams[stream]) > maxlen:
            self.streams[stream] = self.streams[stream][-maxlen:]

        return id

    async def xread(
        self, streams: dict[str, str], count: int | None = None, block: int | None = None
    ) -> list[Any]:
        """Simulate Redis XREAD command."""
        self._record_call("xread", streams, count=count, block=block)
        if self.should_fail:
            raise ConnectionError(self.fail_message)

        await asyncio.sleep(0.001)

        # Simple implementation - return empty for now
        return []

    async def xlen(self, stream: str) -> int:
        """Simulate Redis XLEN command."""
        self._record_call("xlen", stream)
        if self.should_fail:
            raise ConnectionError(self.fail_message)

        await asyncio.sleep(0.001)

        if stream in self.streams:
            return len(self.streams[stream])
        return 0

    async def xrange(
        self, stream: str, start: str = "-", end: str = "+"
    ) -> list[tuple[str, dict[str, str]]]:
        """Simulate Redis XRANGE command."""
        self._record_call("xrange", stream, start, end)
        if self.should_fail:
            raise ConnectionError(self.fail_message)

        await asyncio.sleep(0.001)

        if stream not in self.streams:
            return []

        # Return all entries as tuples of (id, fields)
        result = []
        for entry in self.streams[stream]:
            fields_as_str = {k: str(v) for k, v in entry["fields"].items()}
            result.append((entry["id"], fields_as_str))
        return result

    async def lpush(self, key: str, *values: str) -> int:
        """Simulate Redis LPUSH command."""
        self._record_call("lpush", key, *values)
        if self.should_fail:
            raise ConnectionError(self.fail_message)

        for value in values:
            self.lists[key].insert(0, value)
        return len(self.lists[key])

    async def blpop(self, keys: list[str] | str, timeout: int = 0) -> tuple[str, str] | None:
        """Simulate Redis BLPOP command."""
        # Handle both single key and list of keys
        if isinstance(keys, str):
            keys_list = [keys]
        else:
            keys_list = keys

        self._record_call("blpop", keys_list, timeout=timeout)
        if self.should_fail:
            raise ConnectionError(self.fail_message)

        # Check each key for available items
        for key in keys_list:
            if key in self.lists and self.lists[key]:
                value = self.lists[key].pop(0)
                return (key, value)

        # If timeout is 0, return None immediately (non-blocking)
        # Otherwise simulate waiting
        if timeout > 0:
            await asyncio.sleep(0.1)  # Simulate brief wait

        return None

    async def ping(self) -> bool:
        """Simulate Redis PING command."""
        self._record_call("ping")
        if self.should_fail:
            raise ConnectionError(self.fail_message)

        await asyncio.sleep(0.001)
        return True

    def was_called(self, method_name: str) -> bool:
        """Check if a method was called during testing."""
        return any(call[0] == method_name for call in self.call_history)

    def get_call_args(self, method_name: str) -> tuple[tuple[Any, ...], dict[str, Any]] | None:
        """Get the arguments from the last call to a method."""
        for call in reversed(self.call_history):
            if call[0] == method_name:
                return call[1], call[2]
        return None

    def reset(self) -> None:
        """Clear all data and call history for fresh test state."""
        self.data.clear()
        self.hashes.clear()
        self.sets.clear()
        self.streams.clear()
        self.stream_groups.clear()
        self.expiry.clear()
        self.call_history.clear()

    async def aclose(self) -> None:
        """Simulate closing the Redis connection."""
        self._record_call("aclose")
        # No actual cleanup needed for fake client

    async def xpending(self, stream: str, group: str) -> list[Any]:
        """Simulate Redis XPENDING command."""
        self._record_call("xpending", stream, group)
        if self.should_fail:
            raise ConnectionError(self.fail_message)
        # Return empty pending info for now
        return [0, None, None, []]

    async def xinfo_groups(self, stream: str) -> list[dict[str, Any]]:
        """Simulate Redis XINFO GROUPS command."""
        self._record_call("xinfo_groups", stream)
        if self.should_fail:
            raise ConnectionError(self.fail_message)
        # Return basic group info
        if stream in self.stream_groups:
            return [
                {"name": group, "consumers": 0, "pending": 0, "last-delivered-id": "0-0"}
                for group in self.stream_groups[stream]
            ]
        return []
