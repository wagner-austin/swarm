"""Abstract interface for conversation-history storage backends.

This indirection allows us to swap the concrete implementation (in-memory,
Redis, etc.) without touching call-sites.  All operations are asynchronous so
IO-bound backends (e.g. Redis) don’t block the event-loop even when an
in-memory implementation is used.
"""

from __future__ import annotations

# ruff: noqa: D205,D400

from abc import ABC, abstractmethod
from typing import List, Tuple

# Alias for readability: (user_message, assistant_message)
Turn = Tuple[str, str]


class HistoryBackend(ABC):
    """Abstract storage for conversation turns."""

    @abstractmethod
    async def record(self, channel: int, persona: str, turn: Turn) -> None:  # noqa: D401 – imperative
        """Append *turn* to the tail of the history for *channel* / *persona*."""

    @abstractmethod
    async def recent(self, channel: int, persona: str) -> List[Turn]:
        """Return buffered turns for *channel*/*persona* (oldest first).

        The concrete backend decides how many turns to retain based on the
        *max_turns* value provided to its constructor."""

    @abstractmethod
    async def clear(self, channel: int, persona: str | None = None) -> None:
        """Purge history for *channel* or a specific *persona* within that channel."""
