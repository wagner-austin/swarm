import time
import uuid
from typing import Optional, Any
from bot_core.conversation_store import conversation_store

class Conversation:
    TTL = 3600  # seconds

    def __init__(self, user_id: str, plugin: str, data: Optional[dict] = None):
        self.id = str(uuid.uuid4())
        self.user_id = user_id
        self.plugin = plugin
        self.data = data if data is not None else {}
        self.updated = time.time()

    @classmethod
    async def create(cls, user_id: str, plugin: str, data: Optional[dict] = None):
        self = cls(user_id, plugin, data)
        await conversation_store.add(self)
        return self

    @classmethod
    async def get(cls, user_id: str, plugin: str) -> Optional["Conversation"]:
        return await conversation_store.get(user_id, plugin)

    async def touch(self):
        await conversation_store.touch(self)

    async def remove(self):
        await conversation_store.remove(self)
