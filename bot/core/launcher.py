from __future__ import annotations

import asyncio
import logging

from bot.core.lifecycle import BotLifecycle
from bot.core.settings import settings as global_settings
from bot.frontends.discord.adapter import DiscordFrontendAdapter

# install_handlers import removed – SignalHandlers context manager used instead

logger = logging.getLogger(__name__)

_lifecycle_manager_instance: BotLifecycle | None = None


async def launch_bot() -> None:
    """Initialize settings and start the bot via the BotLifecycle manager.

    This is the primary entry point called by ``main.py``.
    """
    global _lifecycle_manager_instance

    if not global_settings.discord_token:
        logger.critical("DISCORD_TOKEN not configured. Cannot launch bot.")
        return

    _lifecycle_manager_instance = BotLifecycle(settings=global_settings)

    # Expose singleton for alert helpers (bot.core.alerts)
    from bot.core import (
        lifecycle as _lc_mod,
    )  # local import avoids circular import at top level

    _lc_mod._lifecycle_singleton = _lifecycle_manager_instance

    # --- Frontend Adapter Integration ---
    # In the future, select frontend here (Discord, Telegram, Web, etc)
    frontend = DiscordFrontendAdapter(_lifecycle_manager_instance)
    # ------------------------------------

    loop = asyncio.get_running_loop()
    from bot.utils.signals import SignalHandlers

    async with SignalHandlers(loop, _lifecycle_manager_instance):
        await frontend.start()

    logger.info("launch_bot completed.")
