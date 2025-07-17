from __future__ import annotations

from typing import TYPE_CHECKING

from swarm.history.backends import HistoryBackend
from swarm.history.in_memory import MemoryBackend
from swarm.history.redis_backend import RedisBackend

if TYPE_CHECKING:
    from swarm.core.settings import Settings


import logging


def choose(settings: Settings) -> HistoryBackend:
    """
    Select and instantiate the appropriate HistoryBackend.
    Prioritizes Redis if enabled and configured, else falls back to in-memory.
    """
    url = getattr(settings.redis, "url", None)
    if getattr(settings.redis, "enabled", False) and isinstance(url, str) and url:
        logging.info(f"[HistoryBackend] Using RedisBackend for conversation history (url={url})")
        return RedisBackend(
            url,
            max_turns=getattr(settings, "conversation_max_turns", 100),
        )
    logging.info(
        "[HistoryBackend] Using in-memory backend for conversation history (non-persistent)"
    )
    return MemoryBackend(max_turns=getattr(settings, "conversation_max_turns", 100))
