from __future__ import annotations

from collections import defaultdict, deque

from swarm.core.settings import Settings

from .backends import HistoryBackend, Turn


class MemoryBackend(HistoryBackend):
    """Simple in-process ring-buffer implementation of :class:`HistoryBackend`."""

    def __init__(self, max_turns: int | None = None) -> None:
        # Default to Settings.conversation_max_turns to avoid drift with Redis backend configuration.
        # No fallbacks: if Settings() fails, propagate the error to the caller.
        self._max_turns: int = Settings().conversation_max_turns if max_turns is None else max_turns
        # channel_id -> persona -> deque[Turn]
        self._store: dict[int, dict[str, deque[Turn]]] = defaultdict(
            lambda: defaultdict(lambda: deque(maxlen=self._max_turns))
        )

    # ------------------------------------------------------------------
    # Backend API
    # ------------------------------------------------------------------
    async def record(self, channel: int, persona: str, turn: Turn) -> None:  # noqa: D401
        self._store[channel][persona].append(turn)

    async def recent(self, channel: int, persona: str) -> list[Turn]:
        buf: deque[Turn] = self._store[channel][persona]
        # Oldest first so higher-level code can stream messages chronologically.
        return list(buf)

    async def clear(self, channel: int, persona: str | None = None) -> None:  # noqa: D401
        if persona is None:
            self._store.pop(channel, None)
        else:
            self._store[channel].pop(persona, None)
