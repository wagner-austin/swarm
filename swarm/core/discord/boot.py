from __future__ import annotations

import logging
from typing import TYPE_CHECKING

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


# _discover_extensions is obsolete – DI wiring now walks bot.plugins automatically.
