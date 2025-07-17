from __future__ import annotations

import json
import logging
from typing import Any, cast

import redis.asyncio as redis_asyncio

from .backends import (
    HistoryBackend,
    Turn,
)  # must precede runtime code to satisfy ruff E402

# Using `Any` for Redis client type avoids mismatches with stubs that declare
# sync return types (ints, lists) even for async API. This keeps `mypy --strict`
# happy without sprinkling type: ignore comments.
RedisT = Any

logger = logging.getLogger(__name__)


class RedisBackend(HistoryBackend):
    """Redis-based implementation of :class:`HistoryBackend`."""

    def __init__(self, url: str, max_turns: int) -> None:
        self._max_turns = max_turns
        # Decode responses (str) so we get strings not bytes.  Cast keeps mypy strict happy.
        self._r: RedisT = cast(
            RedisT,
            redis_asyncio.from_url(url, encoding="utf-8", decode_responses=True),
        )

    # Internal helper -----------------------------------------------------
    def _key(self, channel: int, persona: str) -> str:
        return f"history:{channel}:{persona}"

    # Backend API ---------------------------------------------------------
    async def record(self, channel: int, persona: str, turn: Turn) -> None:  # noqa: D401
        key: str = self._key(channel, persona)
        await cast(Any, self._r).rpush(key, json.dumps(turn))
        # Trim to last N items (-N to -1 keeps last N)
        await cast(Any, self._r).ltrim(key, -self._max_turns, -1)

    async def recent(self, channel: int, persona: str) -> list[Turn]:
        key: str = self._key(channel, persona)
        raw: list[str] = await cast(Any, self._r).lrange(key, -self._max_turns, -1)
        return cast(list[Turn], [tuple(json.loads(t)) for t in raw])

    async def clear(self, channel: int, persona: str | None = None) -> None:  # noqa: D401
        if persona is None:
            # Wildcard delete using SCAN to avoid blocking KEYS.  Handle both async and sync iterators gracefully.
            pattern = f"history:{channel}:*"
            try:
                iterator = cast(Any, self._r).scan_iter(match=pattern)
                if hasattr(iterator, "__aiter__"):
                    async for key in iterator:
                        await cast(Any, self._r).delete(key)
                else:  # Fallback for sync generator
                    for key in iterator:
                        await cast(Any, self._r).delete(key)
            except Exception as exc:
                # Fallback to KEYS if SCAN not available or fails
                logger.warning(f"Redis SCAN operation failed, falling back to KEYS: {exc}")
                keys = await cast(Any, self._r).keys(pattern)
                if keys:
                    await cast(Any, self._r).delete(*keys)
        else:
            await cast(Any, self._r).delete(self._key(channel, persona))
