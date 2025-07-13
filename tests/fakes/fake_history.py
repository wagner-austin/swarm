"""
Fake History Backend for Testing
=================================

Provides a fake implementation of the history backend that doesn't require
actual Redis infrastructure, enabling fast and reliable unit tests.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class ConversationTurn:
    """Represents a single turn in a conversation."""

    role: str
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)


class FakeHistoryBackend:
    """
    Fake history backend that simulates conversation history storage
    without requiring actual Redis infrastructure.
    """

    def __init__(
        self, should_fail: bool = False, fail_message: str = "Simulated history failure"
    ) -> None:
        self.should_fail = should_fail
        self.fail_message = fail_message
        # Store conversations by (channel_id, user_id) tuple
        self.conversations: dict[tuple[int, int], list[ConversationTurn]] = {}
        self.call_history: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.max_turns = 10  # Default max turns

    def _record_call(self, method_name: str, *args: Any, **kwargs: Any) -> None:
        """Record method calls for test verification."""
        self.call_history.append((method_name, args, kwargs))

    def _get_key(self, channel_id: int, user_id: int) -> tuple[int, int]:
        """Get the conversation key."""
        return (channel_id, user_id)

    async def record(
        self,
        channel_id: int,
        user_id: int,
        user_name: str,
        prompt: str,
        response: str,
        persona: str | None = None,
    ) -> None:
        """Record a conversation turn."""
        self._record_call(
            "record", channel_id, user_id, user_name, prompt, response, persona=persona
        )

        if self.should_fail:
            raise RuntimeError(self.fail_message)

        await asyncio.sleep(0.001)  # Simulate async operation

        key = self._get_key(channel_id, user_id)

        # Initialize conversation if it doesn't exist
        if key not in self.conversations:
            self.conversations[key] = []

        conversation = self.conversations[key]

        # Add user turn
        conversation.append(
            ConversationTurn(
                role="user", content=prompt, metadata={"user_id": user_id, "user_name": user_name}
            )
        )

        # Add assistant turn
        conversation.append(
            ConversationTurn(
                role="assistant", content=response, metadata={"persona": persona} if persona else {}
            )
        )

        # Trim conversation to max turns (pairs of user/assistant)
        if len(conversation) > self.max_turns * 2:
            conversation[:] = conversation[-(self.max_turns * 2) :]

    async def recent(self, channel_id: int, user_id: int, n: int = 5) -> list[dict[str, str]]:
        """Get recent conversation turns."""
        self._record_call("recent", channel_id, user_id, n)

        if self.should_fail:
            raise RuntimeError(self.fail_message)

        await asyncio.sleep(0.001)

        key = self._get_key(channel_id, user_id)
        conversation = self.conversations.get(key, [])

        # Get last n pairs (n*2 turns)
        recent_turns = conversation[-(n * 2) :] if conversation else []

        # Convert to expected format
        result = []
        for turn in recent_turns:
            result.append({"role": turn.role, "content": turn.content})

        return result

    async def clear(self, channel_id: int, user_id: int) -> None:
        """Clear conversation history."""
        self._record_call("clear", channel_id, user_id)

        if self.should_fail:
            raise RuntimeError(self.fail_message)

        await asyncio.sleep(0.001)

        key = self._get_key(channel_id, user_id)
        self.conversations.pop(key, None)

    async def get_all_conversations(self) -> dict[tuple[int, int], list[ConversationTurn]]:
        """Get all conversations (test helper method)."""
        await asyncio.sleep(0.001)
        return dict(self.conversations)

    def get_conversation_count(self) -> int:
        """Get total number of conversations stored."""
        return len(self.conversations)

    def get_turn_count(self, channel_id: int, user_id: int) -> int:
        """Get number of turns in a specific conversation."""
        key = self._get_key(channel_id, user_id)
        return len(self.conversations.get(key, []))

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
        self.conversations.clear()
        self.call_history.clear()

    def set_max_turns(self, max_turns: int) -> None:
        """Set the maximum number of conversation turns to store."""
        self.max_turns = max_turns
