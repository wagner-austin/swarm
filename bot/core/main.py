#!/usr/bin/env python
"""
main.py - Main entry point for the personal Discord bot.
Initializes logging and starts the bot application.
"""

from bot.core.logger_setup import setup_logging
from bot.core.startup import startup
from bot.core.discord_runner import run_bot  # Import run_bot directly
import asyncio


async def main() -> None:
    """
    Main asynchronous entry point.
    Configures logging and delegates to the startup orchestrator.
    """
    setup_logging()
    try:
        proxy_service_instance = await startup()
        await run_bot(proxy_service_instance)  # Pass the instance to run_bot
    except (KeyboardInterrupt, asyncio.CancelledError):
        # Already logged inside run_bot; just make sure we exit quietly.
        pass


# If this script were to be run directly (e.g. `python src/bot_core/main.py`),
# an asyncio.run(main()) call would be needed here, typically guarded by
# if __name__ == "__main__":.
# However, Poetry scripts handle the entry point invocation.
