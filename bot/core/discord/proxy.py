from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot.core.containers import Container
    from bot.core.discord.boot import MyBot  # MyBot is defined in boot.py
    from bot.netproxy.service import ProxyService  # Actual ProxyService class

logger = logging.getLogger(__name__)


async def start_proxy_service_if_enabled(container: Container, bot: MyBot) -> None:
    """Start the ProxyService if enabled in the configuration.

    Update the bot instance and running event loop with the service.
    """
    ps_instance: ProxyService | None = None
    if container.config().proxy_enabled:
        logger.info("Proxy is enabled in settings. Attempting to start ProxyService...")
        try:
            ps_instance = container.proxy_service()  # DI provides the instance
            await ps_instance.start()
            logger.info(f"ProxyService started successfully on port {ps_instance.port}")

            # Store the running proxy service instance on the bot and event loop
            # These assignments are crucial for other parts of the bot to access the service.
            loop = asyncio.get_running_loop()
            setattr(loop, "proxy_service", ps_instance)
            bot.proxy_service = ps_instance

        except Exception as e:
            logger.exception(
                "Failed to start ProxyService during initial setup. It will be unavailable.",
                exc_info=e,
            )
            # Ensure bot.proxy_service is None if startup failed
            bot.proxy_service = None
            # We don't set loop.proxy_service to None here, as it might not have been set.
            # If it was set and then an error occurred, it's a complex state.
            # For now, focus on bot.proxy_service being the primary indicator from this function.
    else:
        logger.info("Proxy is disabled in settings. ProxyService will not be started.")
        bot.proxy_service = None  # Ensure it's None on the bot object

    # No return value needed as we modify bot.proxy_service directly.


async def stop_proxy_service(bot: MyBot) -> None:
    """Stop the ProxyService if it is running and attached to the bot."""
    if bot.proxy_service and hasattr(bot.proxy_service, "stop") and bot.proxy_service.is_running():
        logger.info("Shutting down ProxyService...")
        try:
            await bot.proxy_service.stop()
            logger.info("ProxyService shutdown successfully.")
        except Exception as e:
            logger.exception("Error during ProxyService shutdown:", exc_info=e)
    else:
        logger.info(
            "ProxyService was not running, not attached to the bot, or does not support stop. No shutdown needed."
        )
