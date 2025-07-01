from __future__ import annotations

from typing import TYPE_CHECKING

from bot.history.backends import HistoryBackend
from bot.history.in_memory import MemoryBackend
from bot.history.redis_backend import RedisBackend

if TYPE_CHECKING:
    from bot.core.settings import Settings


def choose(settings: Settings) -> HistoryBackend:
    """
    Select and instantiate the appropriate HistoryBackend.
    Prioritizes Redis if enabled and configured, else falls back to in-memory.
    """
    if getattr(settings, "redis_enabled", False) and hasattr(settings, "redis_url"):
        return RedisBackend(
            settings.redis_url,
            max_turns=getattr(settings, "history_max_turns", 100),
        )
    return MemoryBackend(max_turns=getattr(settings, "history_max_turns", 100))
