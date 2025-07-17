from __future__ import annotations

import asyncio
import logging

from swarm.core.lifecycle import SwarmLifecycle
from swarm.core.settings import settings as global_settings
from swarm.frontends.discord.adapter import DiscordFrontendAdapter

# install_handlers import removed – SignalHandlers context manager used instead

logger = logging.getLogger(__name__)

_lifecycle_manager_instance: SwarmLifecycle | None = None


async def launch_swarm() -> None:
    """Initialize settings and start the bot via the SwarmLifecycle manager.

    This is the primary entry point called by ``main.py``.
    """
    global _lifecycle_manager_instance

    if not global_settings.discord_token:
        logger.critical("DISCORD_TOKEN not configured. Cannot launch bot.")
        return

    _lifecycle_manager_instance = SwarmLifecycle(settings=global_settings)

    # Expose singleton for alert helpers (bot.core.alerts)
    from swarm.core import (
        lifecycle as _lc_mod,
    )  # local import avoids circular import at top level

    _lc_mod._lifecycle_singleton = _lifecycle_manager_instance

    # --- Frontend Adapter Integration ---
    # In the future, select frontend here (Discord, Telegram, Web, etc)
    frontend = DiscordFrontendAdapter(_lifecycle_manager_instance)
    # ------------------------------------

    loop = asyncio.get_running_loop()
    from swarm.utils.signals import SignalHandlers

    async with SignalHandlers(loop, _lifecycle_manager_instance):
        await frontend.start()

    logger.info("launch_swarm completed.")
