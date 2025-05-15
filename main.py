#!/usr/bin/env python
"""
main.py - Main entry point for the Signal bot.
Initializes logging, backups, plugin loading, and starts the SignalBotService.
"""

import asyncio
import os
from core.logger_setup import setup_logging

setup_logging()

import db.schema
import logging
from core.bot_orchestrator import BotOrchestrator

from core.transport_discord import DiscordTransport
from db.backup import create_backup, start_periodic_backups
from core.config import BACKUP_INTERVAL, DISK_BACKUP_RETENTION_COUNT
from plugins.manager import load_plugins

logger = logging.getLogger(__name__)

async def main() -> None:
    # Initialize the SQLite database (creates tables if they do not exist)
    db.schema.init_db()
    
    # Create an automatic backup at startup
    backup_path = create_backup()
    logger.info(f"Startup backup created at: {backup_path}")
    
    # Schedule periodic backups in the background using configurable interval and retention count.
    asyncio.create_task(start_periodic_backups(
        interval_seconds=BACKUP_INTERVAL,
        max_backups=DISK_BACKUP_RETENTION_COUNT))
    
    # Load all plugin modules so that they register their commands.
    load_plugins()

    # Fast exit if environment variable is set (used by tests to avoid infinite loop).
    if os.environ.get("FAST_EXIT_FOR_TESTS") == "1":
        logger.info("FAST_EXIT_FOR_TESTS is set, stopping early for test.")
        return
    
    transport = DiscordTransport()
    bot = BotOrchestrator(transport)
    await bot.start()

if __name__ == "__main__":
    asyncio.run(main())
    logger.info("Bot is up and waiting for Discord events.")

# End of main.py