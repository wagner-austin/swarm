from typing import Any

from swarm.core.lifecycle import SwarmLifecycle
from swarm.frontends.base import FrontendAdapter


class DiscordFrontendAdapter(FrontendAdapter):
    """
    Adapter for running the Discord bot as a frontend.
    Implements the FrontendAdapter interface for future multi-frontend support.
    """

    def __init__(self, lifecycle: SwarmLifecycle) -> None:
        self.lifecycle = lifecycle

    async def start(self) -> None:
        await self.lifecycle.run()

    async def shutdown(self) -> None:
        await self.lifecycle.shutdown(signal_name="frontend_shutdown")

    async def dispatch_message(self, message: Any) -> None:
        # For Discord, most messages are handled via events, but this allows future orchestration.
        pass
