from __future__ import annotations
from collections import deque
from typing import Deque, Dict, List, Tuple

"""Lightweight in-memory conversation history helper.

Stores the last *N* user ↔ model message pairs **per Discord channel and persona**.
This keeps Gemini context short while still offering continuity.

Not persisted between restarts – swap out the internal dict with a real DB/
cache layer (e.g. Redis) if longevity is required.
"""

__all__ = ["ConversationHistory"]

# Alias for readability: (user_message, model_message)
Turn = Tuple[str, str]


class ConversationHistory:
    """Maintain a rolling window of conversation turns."""

    def __init__(self, max_turns: int = 8) -> None:
        self._max_turns = max_turns
        # channel_id -> persona -> deque[Turn]
        self._store: Dict[int, Dict[str, Deque[Turn]]] = {}

    # ---------------------------------------------------------------------
    # Public helpers
    # ---------------------------------------------------------------------
    def record(
        self, channel_id: int, persona: str, user_msg: str, model_msg: str
    ) -> None:
        """Append a new (user, model) turn."""
        channel_buf = self._store.setdefault(channel_id, {})
        persona_buf = channel_buf.setdefault(persona, deque(maxlen=self._max_turns))
        persona_buf.append((user_msg, model_msg))

    def get(self, channel_id: int, persona: str) -> List[Turn]:
        """Return list of recent turns – oldest first."""
        return list(self._store.get(channel_id, {}).get(persona, []))

    def clear(self, channel_id: int, persona: str | None = None) -> None:
        """Clear history for a channel, or for a specific persona in that channel."""
        if persona is None:
            self._store.pop(channel_id, None)
        else:
            self._store.get(channel_id, {}).pop(persona, None)
