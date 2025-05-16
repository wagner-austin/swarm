import asyncio
import logging
from discord import Intents
from discord.ext import commands
from pathlib import Path
from bot_core.logger_setup import setup_logging
from bot_core.settings import Settings


def _discover_extensions() -> list[str]:
    """Return all extension module paths for commands and maintenance cogs.

    Returns:
        list[str]: Fully-qualified module names for all command and maintenance cogs.
    """
    root = Path(__file__).parent / "bot_plugins" / "commands"
    extensions = [
        f"bot_plugins.commands.{p.stem}"
        for p in root.glob("*.py")
        if p.stem != "__init__"
    ]
    # Always include the maintenance cog
    extensions.append("bot_plugins.maintenance")
    return extensions


logger = logging.getLogger(__name__)


async def run() -> None:
    """Set up logging, load all extensions, and start the Discord bot."""
    setup_logging()
    intents = Intents.default()
    bot = commands.Bot(command_prefix=commands.when_mentioned_or("!"), intents=intents)

    for ext in _discover_extensions():
        try:
            await bot.load_extension(ext)
        except Exception:
            logger.exception("Failed to load %s", ext)

    settings = Settings(discord_token="YOUR_TOKEN_HERE")
    token = settings.discord_token
    await bot.start(token)


async def amain() -> None:
    setup_logging()
    intents = Intents.default()
    bot = commands.Bot(command_prefix=commands.when_mentioned_or("!"), intents=intents)
    for ext in _discover_extensions():
        try:
            await bot.load_extension(ext)
        except Exception:
            logger.exception("Failed to load %s", ext)
    settings = Settings(discord_token="YOUR_TOKEN_HERE")
    token = settings.discord_token
    await bot.start(token)


if __name__ == "__main__":
    import asyncio

    asyncio.run(amain())
