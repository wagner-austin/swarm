from typing import Any

from bot_core.transport import Transport

import logging

from bot_core.settings import Settings

class BotOrchestrator:
    def __init__(self, transport: Transport, settings: Settings):
        self.transport = transport
        self.settings = settings
        from bot_core.message_manager import MessageManager
        self._mm = MessageManager(settings=self.settings)
        logging.getLogger(__name__).info("BotOrchestrator initialised")

    async def _send(self, ctx, content: str):
        if hasattr(ctx, "channel"):
            await self.transport.send_message(ctx.channel, content)
        else:
            await self.transport.send_message(ctx, content)

    async def dispatch(self, parsed, ctx: Any):
        result = await self._mm.process_message(parsed, ctx)
        if result:
            await self._send(ctx, result)

    async def start(self):
        await self.transport.start(self.dispatch)

