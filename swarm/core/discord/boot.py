from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from discord import Intents
from discord.ext import commands

# This import is for type hinting MyBot.proxy_service.
# We should check this later, but for now, it's needed for the type hint.

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from swarm.core.containers import Container
    from swarm.core.lifecycle import SwarmLifecycle
    from swarm.core.settings import Settings


class MyBot(commands.Bot):
    # Attrs assigned by wiring after construction.
    container: Container | None = None
    lifecycle: SwarmLifecycle
    settings: Settings | None = None
    proxy_service: object | None = None

    def __init__(
        self,
        *,
        command_prefix: str,
        intents: Intents,
        container: Container | None = None,
        settings: Settings | None = None,
    ) -> None:
        """Initialize bot with explicit DI context.

        The lifecycle passes the DI ``container`` and runtime ``settings`` so
        cogs added through the container can reliably access shared providers.
        """
        super().__init__(command_prefix=command_prefix, intents=intents)
        self.container = container
        self.settings = settings


# _discover_extensions is obsolete – DI wiring now walks bot.plugins automatically.
