#!/usr/bin/env python
"""
main.py - Main entry point for the Signal bot.
Initializes logging, backups, plugin loading, and starts the SignalBotService.
"""

import asyncio
import os
import logging

import logging
from bot_core.bot_orchestrator import BotOrchestrator
from bot_core.settings import settings

from db.backup import create_backup, start_periodic_backups
from bot_plugins.manager import load_plugins

logger = logging.getLogger(__name__)

async def main() -> None:
    # Initialize the SQLite database (creates tables if they do not exist)
    import subprocess, pathlib, os
    # Always use the correct alembic.ini location and run from project root
    project_root = pathlib.Path(__file__).resolve().parent.parent
    alembic_ini = project_root / "migrations" / "alembic.ini"

    # Always use DB_URL from environment
    env = os.environ.copy()
    db_url = env.get("DB_URL")
    if db_url:
        env["DB_URL"] = db_url
    # Ensure PYTHONPATH includes the project root so 'migrations' is importable
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [
            "alembic", "-c", str(alembic_ini), "upgrade", "head"
        ],
        cwd=str(project_root),
        capture_output=True,
        text=True,
        env=env
    )
    if result.returncode != 0:
        print("Alembic failed:\n", result.stdout, result.stderr)
        raise RuntimeError(f"Alembic failed with exit code {result.returncode}")

    # Create an automatic backup at startup
    backup_path = create_backup()
    logger.info(f"Startup backup created at: {backup_path}")
    
    # Schedule periodic backups in the background using configurable interval and retention count.
    asyncio.create_task(start_periodic_backups(cfg=settings))
    
    # Load all plugin modules so that they register their commands.
    load_plugins()

    # Fast exit if environment variable is set (used by tests to avoid infinite loop).
    if os.environ.get("FAST_EXIT_FOR_TESTS") == "1":
        logger.info("FAST_EXIT_FOR_TESTS is set, stopping early for test.")
        return

    from bot_core.transport_discord import DiscordTransport
    transport = DiscordTransport(settings=settings)
    bot = BotOrchestrator(transport, settings=settings)
    await bot.start()

if __name__ == "__main__":
    asyncio.run(main())
    logger.info("Bot is up and waiting for Discord events.")

# End of main.py