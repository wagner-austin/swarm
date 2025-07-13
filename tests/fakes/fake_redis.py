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

        await asyncio.sleep(0.001)

        # Simulate consumer group creation
        if stream not in self.streams and not mkstream:
            raise Exception("ERR no such key")

        if stream not in self.streams:
            self.streams[stream] = []

    async def xadd(self, stream: str, fields: dict[str, Any], id: str = "*") -> str:
        """Simulate Redis XADD command."""
        self._record_call("xadd", stream, fields, id=id)
        if self.should_fail:
            raise ConnectionError(self.fail_message)

        await asyncio.sleep(0.001)

        # Generate ID if not specified
        if id == "*":
            id = f"{int(time.time() * 1000)}-0"

        self.streams[stream].append({"id": id, "fields": fields})
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
        self.expiry.clear()
        self.call_history.clear()
