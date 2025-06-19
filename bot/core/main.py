#!/usr/bin/env python
"""
main.py - Main entry point for the personal Discord bot.
Initializes logging and starts the bot application.
"""

from bot.core.launcher import launch_bot  # Import launch_bot from new launcher


async def main() -> None:
    """
    Main asynchronous entry point.
    Configures logging and delegates to the startup orchestrator.
    """
    # Logging is configured during the initial bootstrap in bot.core.__main__.
    # The new launch_bot and BotLifecycle handle KeyboardInterrupt/CancelledError internally.
    await launch_bot()


# If this script were to be run directly (e.g. `python src/bot_core/main.py`),
# an asyncio.run(main()) call would be needed here, typically guarded by
# if __name__ == "__main__":.
# However, Poetry scripts handle the entry point invocation.
