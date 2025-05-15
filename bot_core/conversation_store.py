"""
bot_core.conversation_store
---------------------------
In-memory implementation of a *conversation registry* with pluggable storage.
Later we can replace the private dict with a DB table or Redis without touching
call-sites.
"""
from __future__ import annotations
import asyncio
import time
from typing import Dict, Optional, Iterable

class ConversationStore:
    def __init__(self, ttl: int = 3600, cleanup_interval: int = 60):
        self._ttl = ttl
        self._store: Dict[str, "Conversation"] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None
        self._cleanup_interval = cleanup_interval

    # ---------- public API -------------------------------------------------
    async def get(self, user_id: str, plugin: str) -> Optional["Conversation"]:
        await self._expire()
        conv_id = self._make_key(user_id, plugin)
        return self._store.get(conv_id)

    async def add(self, convo: "Conversation") -> None:
        async with self._lock:
            self._store[self._key(convo)] = convo

    async def touch(self, convo: "Conversation") -> None:
        convo.updated = time.time()

    async def remove(self, convo: "Conversation") -> None:
        async with self._lock:
            self._store.pop(self._key(convo), None)

    async def clear(self) -> None:        # helper for tests
        async with self._lock:
            self._store.clear()

    def start_background_cleanup(self) -> None:
        if self._cleanup_task and not self._cleanup_task.done():
            return                            # already running
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    # ---------- internals --------------------------------------------------
    async def _expire(self) -> None:
        now = time.time()
        async with self._lock:
            for key, convo in list(self._store.items()):
                if now - convo.updated > self._ttl:
                    self._store.pop(key, None)

    async def _cleanup_loop(self) -> None:
        while True:
            await self._expire()
            await asyncio.sleep(self._cleanup_interval)

    # key helpers -----------------------------------------------------------
    @staticmethod
    def _make_key(user_id: str, plugin: str) -> str:
        return f"{user_id}:{plugin}"

    def _key(self, convo: "Conversation") -> str:           # noqa: D401
        return self._make_key(convo.user_id, convo.plugin)


# a singleton instance used by production code and tests
conversation_store = ConversationStore()
