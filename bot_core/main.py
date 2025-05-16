#!/usr/bin/env python
"""
main.py - Main entry point for the personal Discord bot.
Initializes logging, backups, plugin loading, and starts the Discord bot service.
"""

from pathlib import Path
import asyncio
import logging
import subprocess
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


async def main() -> None:
    """Main entry point to prepare the database, create a backup, and start the bot."""
    await _prep_db()
    backup_path = create_backup()
    logger.info("Startup backup at %s", backup_path)
    if os.environ.get("FAST_EXIT_FOR_TESTS") == "1":
        return
    import bot

    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
    logger.info("Bot is up and waiting for Discord events.")

# End of main.py
