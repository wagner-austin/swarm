"""
Thin launcher kept for backward compatibility.
Real startup logic now lives in bot_core.main.
"""

from .bot_core.main import main as _main


async def run() -> None:  # keeps the original public symbol alive
    await _main()


if __name__ == "__main__":
    import asyncio
    import signal
    import sys
    import logging
    from typing import Any

    # Set up cleaner Ctrl+C handling
    def signal_handler(sig: int, frame: Any) -> None:
        logging.info("Shutdown signal received, exiting gracefully...")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as e:
        logging.exception(f"Unexpected error: {e}")
        sys.exit(1)
