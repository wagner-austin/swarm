"""
Thin launcher kept for backward compatibility.
Real startup logic now lives in bot_core.main.
"""

from bot_core.main import main as _main


async def run() -> None:  # keeps the original public symbol alive
    await _main()


if __name__ == "__main__":
    import asyncio

    asyncio.run(_main())
