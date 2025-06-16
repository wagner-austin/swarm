from __future__ import annotations

import asyncio
import logging
import os
import signal
from typing import Callable

from bot.core.logger_setup import setup_logging
from bot.core.settings import settings as global_settings
from bot.core.lifecycle import BotLifecycle

# Ensure logging is configured before any loggers are fetched
setup_logging()

logger = logging.getLogger(__name__)

_lifecycle_manager_instance: BotLifecycle | None = None


async def _handle_signal(sig: signal.Signals, manager: BotLifecycle) -> None:
    logger.info(f"Received signal {sig.name}, initiating graceful shutdown...")
    # Create a task to ensure shutdown runs even if current handler context is tricky
    asyncio.create_task(manager.shutdown(signal_name=sig.name))


async def launch_bot() -> None:
    """
    Initializes settings and starts the bot using the BotLifecycle manager.
    This is the primary entry point called by main.py.
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

    signals_to_handle: list[signal.Signals] = [signal.SIGINT]
    if os.name != "nt":  # SIGTERM is not really a thing for console apps on Windows
        signals_to_handle.append(signal.SIGTERM)

    for sig in signals_to_handle:

        def _register_sig_handler(sig_to_use: signal.Signals) -> Callable[[], None]:
            """Return a zero-arg callable suitable for add_signal_handler."""

            def _handler() -> None:  # pragma: no cover – only runs on real signal
                asyncio.create_task(
                    _handle_signal(sig_to_use, _lifecycle_manager_instance)
                )

            return _handler

        try:
            loop.add_signal_handler(sig, _register_sig_handler(sig))
            logger.info(f"Registered signal handler for {sig.name}")
        except (NotImplementedError, AttributeError, ValueError, RuntimeError) as e:
            logger.warning(
                f"Could not set {sig.name} handler: {e}. Graceful shutdown via this signal may not work."
            )

    await _lifecycle_manager_instance.run()

    # Clean up signal handlers after run completes (bot has stopped)
    # This is important if the event loop is reused or for testing environments
    for sig in signals_to_handle:
        try:
            loop.remove_signal_handler(sig)
            logger.info(f"Removed signal handler for {sig.name}")
        except (NotImplementedError, AttributeError, ValueError, RuntimeError) as e:
            logger.debug(f"Could not remove {sig.name} handler during cleanup: {e}")

    logger.info("launch_bot completed.")
