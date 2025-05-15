#!/usr/bin/env python
"""
main.py - Main entry point for the Signal bot.
Initializes logging, backups, plugin loading, and starts the SignalBotService.
"""

import os
import asyncio
import logging
import pathlib
import subprocess
from bot_core.settings import settings
from db.backup import create_backup

logger = logging.getLogger(__name__)

async def _prep_db() -> None:
    project_root = pathlib.Path(__file__).resolve().parent.parent
    alembic_ini = project_root / "migrations" / "alembic.ini"
    env = os.environ.copy()
    if settings.db_name:
        env["DB_URL"] = env.get("DB_URL", f"sqlite+aiosqlite:///{settings.db_name}")
    result = subprocess.run(
        ["alembic", "-c", str(alembic_ini), "upgrade", "head"],
        cwd=str(project_root),
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode:
        raise RuntimeError(result.stderr)

async def main() -> None:
    await _prep_db()
    backup_path = create_backup()
    logging.getLogger(__name__).info("Startup backup at %s", backup_path)
    if os.environ.get("FAST_EXIT_FOR_TESTS") == "1":
        return
    import bot; bot.run()

if __name__ == "__main__":
    asyncio.run(main())
    logger.info("Bot is up and waiting for Discord events.")

# End of main.py