from __future__ import annotations

import asyncio
import logging

from bot.core.lifecycle import BotLifecycle
from bot.core.settings import settings as global_settings
from bot.utils.signals import install_handlers

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

    loop = asyncio.get_running_loop()

    # install OS signal handlers via shared helper
    installed_sigs = install_handlers(loop, _lifecycle_manager_instance)

    await _lifecycle_manager_instance.run()

    # Clean up signal handlers after run completes (bot has stopped)
    for sig in installed_sigs:
        try:
            loop.remove_signal_handler(sig)
            logger.info(f"Removed signal handler for {sig.name}")
        except (NotImplementedError, AttributeError, ValueError, RuntimeError) as e:
            logger.debug(f"Could not remove {sig.name} handler during cleanup: {e}")

    logger.info("launch_bot completed.")
