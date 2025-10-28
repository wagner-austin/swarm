from __future__ import annotations

import json
import logging

import redis.asyncio as redis_asyncio

from swarm.infra.redis_protocols import RedisAsyncProtocol, wrap_redis_async

from .backends import (
    HistoryBackend,
    Turn,
)  # must precede runtime code to satisfy ruff E402

logger = logging.getLogger(__name__)


class RedisBackend(HistoryBackend):
    """Redis-based implementation of :class:`HistoryBackend`."""

    def __init__(self, url: str, max_turns: int) -> None:
        self.url: str = url  # Store URL for introspection
        self._max_turns = max_turns

        # Decode responses (str) so we get strings not bytes.
        inner = redis_asyncio.from_url(url, encoding="utf-8", decode_responses=True)
        self._r: RedisAsyncProtocol = wrap_redis_async(inner)

    # Internal helper -----------------------------------------------------
    def _key(self, channel: int, persona: str) -> str:
        return f"history:{channel}:{persona}"

    # Backend API ---------------------------------------------------------
    async def record(self, channel: int, persona: str, turn: Turn) -> None:  # noqa: D401
        key: str = self._key(channel, persona)
        await self._r.rpush(key, json.dumps(turn))
        # Trim to last N items (-N to -1 keeps last N)
        await self._r.ltrim(key, -self._max_turns, -1)

    async def recent(self, channel: int, persona: str) -> list[Turn]:
        key: str = self._key(channel, persona)
        raw: list[str] = await self._r.lrange(key, -self._max_turns, -1)

        def _deserialize_turn(s: str) -> Turn:
            obj = json.loads(s)
            if (isinstance(obj, list) or isinstance(obj, tuple)) and len(obj) == 2:
                a, b = obj[0], obj[1]
                if isinstance(a, str) and isinstance(b, str):
                    # Ensure concrete tuple[str, str]
                    return (a, b)
            raise ValueError("Invalid Turn payload")

        return [_deserialize_turn(t) for t in raw]

    async def clear(self, channel: int, persona: str | None = None) -> None:  # noqa: D401
        if persona is None:
            # Wildcard delete using SCAN to avoid blocking KEYS.  Handle both async and sync iterators gracefully.
            pattern = f"history:{channel}:*"
            try:
                async for key in self._r.scan_iter(match=pattern):
                    await self._r.delete(key)
            except Exception as exc:
                # Fallback to KEYS if SCAN not available or fails
                logger.warning(f"Redis SCAN operation failed, falling back to KEYS: {exc}")
                keys = await self._r.keys(pattern)
                if keys:
                    await self._r.delete(*keys)
        else:
            await self._r.delete(self._key(channel, persona))
