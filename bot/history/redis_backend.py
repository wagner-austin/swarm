from __future__ import annotations

import json
from typing import List

try:
    import aioredis
except ModuleNotFoundError:  # pragma: no cover – optional dependency
    aioredis = None


from .backends import HistoryBackend, Turn


class RedisBackend(HistoryBackend):
    """Redis-based implementation of :class:`HistoryBackend`."""

    def __init__(self, url: str, max_turns: int) -> None:
        if aioredis is None:
            raise ImportError(
                "aioredis dependency required for RedisBackend but not installed.\nInstall via `pip install aioredis`. "
            )
        self._max_turns = max_turns
        # Decode responses (str) so we get strings not bytes
        self._r: aioredis.Redis[str] = aioredis.from_url(url, decode_responses=True)

    # Internal helper -----------------------------------------------------
    def _key(self, channel: int, persona: str) -> str:
        return f"history:{channel}:{persona}"

    # Backend API ---------------------------------------------------------
    async def record(self, channel: int, persona: str, turn: Turn) -> None:  # noqa: D401
        key: str = self._key(channel, persona)
        await self._r.rpush(key, json.dumps(turn))
        # Trim to last N items (-N to -1 keeps last N)
        await self._r.ltrim(key, -self._max_turns, -1)

    async def recent(self, channel: int, persona: str) -> List[Turn]:
        key: str = self._key(channel, persona)
        raw: List[str] = await self._r.lrange(key, -self._max_turns, -1)
        from typing import cast

        return cast(List[Turn], [tuple(json.loads(t)) for t in raw])

    async def clear(self, channel: int, persona: str | None = None) -> None:  # noqa: D401
        if persona is None:
            # Wildcard delete
            keys = await self._r.keys(f"history:{channel}:*")
            if keys:
                await self._r.delete(*keys)
        else:
            await self._r.delete(self._key(channel, persona))
