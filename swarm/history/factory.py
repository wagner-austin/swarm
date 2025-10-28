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
    Select the conversation HistoryBackend with no silent fallbacks.

    - If Redis is enabled, a valid URL is required.
    - If Redis is disabled, raise to avoid non-persistent history by accident.
    """
    url = getattr(settings.redis, "url", None)
    enabled = getattr(settings.redis, "enabled", False)
    if enabled:
        if not isinstance(url, str) or not url:
            raise RuntimeError("[HistoryBackend] REDIS__URL must be set when REDIS__ENABLED=true")
        logging.info(f"[HistoryBackend] Using RedisBackend for conversation history (url={url})")
        return RedisBackend(
            url,
            max_turns=getattr(settings, "conversation_max_turns", 100),
        )
    # No fallback – fail fast so operators configure persistence explicitly
    raise RuntimeError(
        "[HistoryBackend] Redis is required for chat history persistence. "
        "Set REDIS__ENABLED=true and REDIS__URL in the environment."
    )
