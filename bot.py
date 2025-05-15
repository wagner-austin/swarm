import importlib
import logging
from pathlib import Path
from discord.ext import commands
from bot_core.logger_setup import setup_logging
from bot_core.settings import settings

def _discover_extensions() -> list[str]:
    """Return every fully-qualified module in bot_plugins.commands.* and bot_plugins.maintenance."""
    root = Path(__file__).parent / "bot_plugins" / "commands"
    extensions = [
        f"bot_plugins.commands.{p.stem}"
        for p in root.glob("*.py")
        if p.stem != "__init__"
    ]
    # Always include the maintenance cog
    extensions.append("bot_plugins.maintenance")
    return extensions

def run() -> None:
    setup_logging()
    bot = commands.Bot(command_prefix=commands.when_mentioned_or("!"))

    for ext in _discover_extensions():
        try:
            bot.load_extension(ext)
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).exception("Failed to load %s", ext)

    token = settings.discord_token
    bot.run(token)

if __name__ == "__main__":  # pragmatic local run
    run()
