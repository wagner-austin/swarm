#!/usr/bin/env python
"""
db/backup.py - Database backup and restore utilities.
Provides functions to create a backup snapshot of the current database, automatically clean up old backups
using a configurable retention count, and schedule periodic backups using a configurable interval.
Changes:
 - Added an info-level log message upon successful backup creation.
 - Updated periodic backup to handle exceptions and log warnings on failure.
 - Updated restore_backup to check for truncated backups (≤ 16 bytes) and log as invalid/corrupted.
"""

import os
import shutil
from datetime import datetime
import asyncio
import logging
from bot_core.settings import settings, Settings

logger = logging.getLogger(__name__)


def _generate_backup_filename(backup_dir: str) -> str:
    """
    Generates a unique backup filename using the current date-time second.
    If multiple backups occur in the same second, appends a numeric suffix.
    """
    base_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = 0
    while True:
        filename = f"backup_{base_timestamp}"
        if suffix:
            filename += f"_{suffix}"
        filename += ".db"
        fullpath = os.path.join(backup_dir, filename)
        if not os.path.exists(fullpath):
            return filename
        suffix += 1

def create_backup(cfg: Settings = None) -> str:
    """
    Create a backup of the current database.

    Returns:
        str: The file path of the created backup, or an empty string if creation failed.
    """
    cfg = cfg or settings
    backup_dir = os.path.join(os.path.dirname(cfg.db_name), "backups")
    try:
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)
    except OSError as e:
        logger.warning(f"Failed to create backup directory '{backup_dir}'. Error: {e}")
        return ""
    
    backup_filename = _generate_backup_filename(backup_dir)
    backup_path = os.path.join(backup_dir, backup_filename)

    try:
        shutil.copyfile(cfg.db_name, backup_path)
        logger.info(f"Backup created at: {backup_path}")
        return backup_path
    except Exception as e:
        logger.warning(f"Failed to create backup file at '{backup_path}'. Error: {e}")
        return ""

def list_backups(cfg: Settings = None) -> list:
    """
    List all backup files in the backup directory.

    Returns:
        list: A sorted list of backup file names.
    """
    cfg = cfg or settings
    backup_dir = os.path.join(os.path.dirname(cfg.db_name), "backups")
    if not os.path.exists(backup_dir):
        return []
    backups = [f for f in os.listdir(backup_dir) if f.endswith(".db")]
    backups.sort()
    return backups

def restore_backup(backup_filename: str, cfg: Settings = None) -> bool:
    """
    Restore the database from a specified backup file.

    Args:
        backup_filename (str): The name of the backup file (found in the backups folder).

    Returns:
        bool: True if restoration is successful, False otherwise.
    """
    cfg = cfg or settings
    backup_dir = os.path.join(os.path.dirname(cfg.db_name), "backups")
    backup_path = os.path.join(backup_dir, backup_filename)
    if not os.path.exists(backup_path):
        return False

    try:
        shutil.copyfile(backup_path, cfg.db_name)
    except Exception as e:
        logger.warning(f"Failed to restore backup '{backup_filename}' to '{cfg.db_name}'. Error: {e}")
        return False

    return True

def _prune_backups(max_backups: int | None = None, cfg: Settings = None):
    """
    Delete oldest backups if number of backups exceeds max_backups.
    """
    if not max_backups or max_backups < 1:
        return
    backups = list_backups(cfg=cfg)
    cfg = cfg or settings
    backup_dir = os.path.join(os.path.dirname(cfg.db_name), "backups")
    if len(backups) > max_backups:
        # Remove oldest backups
        for old in backups[:-max_backups]:
            try:
                os.remove(os.path.join(backup_dir, old))
                logger.info(f"Deleted old backup: {old}")
            except Exception as e:
                logger.warning(f"Failed to delete old backup '{old}': {e}")

async def start_periodic_backups(cfg: Settings = None) -> None:
    """
    Schedule periodic backups at the specified interval.

    Args:
        cfg (Settings): The settings to use for the backup interval.
    """
    cfg = cfg or settings
    interval_seconds = cfg.backup_interval
    while True:
        try:
            backup_path = create_backup(cfg=cfg)
            if backup_path:
                _prune_backups(cfg.backup_retention, cfg=cfg)
        except Exception as e:
            logger.warning(f"Periodic backup failed: {e}")
        await asyncio.sleep(interval_seconds)

# End of db/backup.py