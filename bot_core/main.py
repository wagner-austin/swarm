#!/usr/bin/env python
"""
main.py - Main entry point for the personal Discord bot.
Initializes logging, backups, plugin loading, and starts the Discord bot service.
"""

import logging
import subprocess
from discord import Intents
from discord.ext import commands
from pathlib import Path
from bot_core.logger_setup import setup_logging
from bot_core.settings import settings  # fully typed alias
from db.backup import create_backup
import os

logger = logging.getLogger(__name__)


async def _prep_db() -> None:
    """Run Alembic migrations to ensure the database schema is up to date.

    Raises:
        RuntimeError: If Alembic migration fails.
    """
    project_root = Path(__file__).resolve().parents[1]
    alembic_ini = project_root / "migrations" / "alembic.ini"
    env = os.environ.copy()
    if settings.db_name:
        env["DB_URL"] = env.get("DB_URL", f"sqlite+aiosqlite:///{settings.db_name}")
    result = subprocess.run(
        ["alembic", "-c", str(alembic_ini), "upgrade", "head"],
        cwd=project_root,
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode:
        raise RuntimeError(result.stderr)


def _discover_extensions() -> list[str]:
    root = Path(__file__).resolve().parent.parent / "bot_plugins" / "commands"
    return [
        f"bot_plugins.commands.{p.stem}"
        for p in root.glob("*.py")
        if p.stem != "__init__"
    ] + ["bot_plugins.maintenance"]


async def _start_bot() -> None:
    # Configure intents
    intents = Intents.default()
    # Add message content intent to ensure commands work properly
    intents.message_content = True

    # Create bot instance
    bot = commands.Bot(
        command_prefix=commands.when_mentioned_or("!"),
        intents=intents,
        case_insensitive=True,
    )

    # Remove the built-in help command before loading our custom one
    bot.remove_command("help")

    # Load extensions
    for ext in _discover_extensions():
        try:
            await bot.load_extension(ext)
        except Exception:
            logger.exception("Failed to load %s", ext)

    # Setup clean close handler
    @bot.event
    async def on_disconnect() -> None:
        logger.info("Bot disconnected from Discord")

    # Start the bot
    try:
        await bot.start(settings.discord_token)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    finally:
        if not bot.is_closed():
            await bot.close()
            logger.info("Bot connection closed")


async def main() -> None:
    """Main entry point to prepare the database, create a backup, and start the bot."""
    setup_logging()  # new – configure logging once
    try:
        await _prep_db()
        backup_path = create_backup()
        logger.info("Startup backup at %s", backup_path)
        if os.environ.get("FAST_EXIT_FOR_TESTS") == "1":
            return
        await _start_bot()  # replaces the import-bot indirection
    except KeyboardInterrupt:
        logger.info("Bot shutting down gracefully (KeyboardInterrupt received)")
    except Exception as e:
        logger.exception("Unexpected error: %s", str(e))
    finally:
        # Ensure proper cleanup here
        logger.info("Bot has been shut down")
        # Additional cleanup code can be added here if needed


# End of main.py
