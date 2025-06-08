# src/bot_core/startup.py
import logging
import os

from bot.core.settings import settings
from bot.infra.tankpit.proxy.service import ProxyService

logger = logging.getLogger(__name__)


async def startup() -> ProxyService | None:
    """
    Orchestrates the startup sequence: database preparation, backup,
    proxy service initialization, and bot launch.
    Handles top-level error catching and resource cleanup.
    """
    proxy_service_instance: ProxyService | None = None
    try:
        # (DB layer removed – backup logic no longer exists)

        if os.environ.get("FAST_EXIT_FOR_TESTS") == "1":
            logger.info("FAST_EXIT_FOR_TESTS is set. Aborting full startup.")
            return None

        # If `settings.proxy_port` is None, fall back to 9000
        proxy_port = settings.proxy_port or 9000
        proxy_service_instance = ProxyService(port=proxy_port)
        logger.info(f"ProxyService initialized, configured for port: {proxy_port}")
        # Proxy service will be started later by the bot itself in on_ready

        # await run_bot(proxy_service_instance) # This will be called from main.py

    except KeyboardInterrupt:
        logger.info("Shutdown initiated by KeyboardInterrupt (Ctrl+C).")
        return None  # Ensure we return None on KeyboardInterrupt
    except Exception as e:
        logger.exception(
            "A critical error occurred during startup or bot operation: %s", str(e)
        )
        return None  # Ensure we return None on exception before finally

    return proxy_service_instance
