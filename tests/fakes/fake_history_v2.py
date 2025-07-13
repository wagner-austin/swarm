"""
Fake History Backend for Testing (V2)
======================================

Provides a fake implementation of the history backend that matches
the actual HistoryBackend interface.
"""

import asyncio
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Tuple

# Match the actual Turn type from backends.py
Turn = tuple[str, str]  # (role, content)


class FakeHistoryBackendV2:
    """
    Fake history backend that matches the real HistoryBackend interface.
    """

    def __init__(
        self,
        max_turns: int = 10,
        should_fail: bool = False,
        fail_message: str = "Simulated history failure",
    ) -> None:
        self.max_turns = max_turns
        self.should_fail = should_fail
        self.fail_message = fail_message
        # channel -> persona -> deque[Turn]
        self._store: dict[int, dict[str, deque[Turn]]] = defaultdict(
            lambda: defaultdict(lambda: deque(maxlen=max_turns))
        )
        self.call_history: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def _record_call(self, method_name: str, *args: Any, **kwargs: Any) -> None:
        """Record method calls for test verification."""
        self.call_history.append((method_name, args, kwargs))

    async def record(self, channel: int, persona: str, turn: Turn) -> None:
        """Append turn to the tail of the history for channel/persona."""
        self._record_call("record", channel, persona, turn)

        if self.should_fail:
            raise RuntimeError(self.fail_message)

        await asyncio.sleep(0.001)  # Simulate async operation
        self._store[channel][persona].append(turn)

    async def recent(self, channel: int, persona: str) -> list[Turn]:
        """Return buffered turns for channel/persona (oldest first)."""
        self._record_call("recent", channel, persona)

        if self.should_fail:
            raise RuntimeError(self.fail_message)

        await asyncio.sleep(0.001)
        buf = self._store[channel][persona]
        # Return oldest first like the real implementation
        return list(buf)

    async def clear(self, channel: int, persona: str) -> None:
        """Clear history for channel/persona."""
        self._record_call("clear", channel, persona)

        if self.should_fail:
            raise RuntimeError(self.fail_message)

        await asyncio.sleep(0.001)
        if channel in self._store and persona in self._store[channel]:
            self._store[channel][persona].clear()

    # Test helper methods
    def get_turn_count(self, channel: int, persona: str) -> int:
        """Get number of turns in a specific conversation."""
        return len(self._store[channel][persona])

    def was_called(self, method_name: str) -> bool:
        """Check if a method was called during testing."""
        return any(call[0] == method_name for call in self.call_history)

    def get_call_args(self, method_name: str) -> tuple[tuple[Any, ...], dict[str, Any]] | None:
        """Get the arguments from the last call to a method."""
        for call in reversed(self.call_history):
            if call[0] == method_name:
                return call[1], call[2]
        return None

    def get_call_count(self, method_name: str) -> int:
        """Get the number of times a method was called."""
        return sum(1 for call in self.call_history if call[0] == method_name)

    def reset(self) -> None:
        """Clear all data and call history for fresh test state."""
        self._store.clear()
        self.call_history.clear()
