import time
import uuid
from typing import Optional, Dict, Any

_WIZARDS: Dict[str, "Conversation"] = {}

class Conversation:
    TTL = 3600  # seconds

    def __init__(self, user_id: str, plugin: str, data: Optional[dict] = None):
        self.id = str(uuid.uuid4())
        self.user_id = user_id
        self.plugin = plugin
        self.data = data if data is not None else {}
        self.updated = time.time()
        _WIZARDS[self.id] = self

    @classmethod
    def get(cls, user_id: str, plugin: str) -> Optional["Conversation"]:
        now = time.time()
        # Copy to avoid modifying dict during iteration
        for w in list(_WIZARDS.values()):
            if now - w.updated > cls.TTL:
                del _WIZARDS[w.id]
                continue
            if w.user_id == user_id and w.plugin == plugin:
                return w
        return None

    def touch(self):
        self.updated = time.time()
