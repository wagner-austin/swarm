from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from discord.ext import commands

# This import is for type hinting MyBot.proxy_service.
# We should check this later, but for now, it's needed for the type hint.

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from swarm.core.containers import Container
    from swarm.core.lifecycle import SwarmLifecycle
    from swarm.core.settings import Settings


class MyBot(commands.Bot):
    # Attrs added at runtime, but mypy needs to know for strict type checking.
    container: Container
    lifecycle: SwarmLifecycle
    settings: Settings

    def __init__(self, *args: Any, **kwargs: Any):
        # Extract our custom parameters before passing to parent
        self.container = kwargs.pop("container", None)
        self.settings = kwargs.pop("settings", None)

        super().__init__(*args, **kwargs)
        self.proxy_service = None


# _discover_extensions is obsolete – DI wiring now walks bot.plugins automatically.
