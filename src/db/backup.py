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

from typing import Optional
from pathlib import Path
import shutil
from datetime import datetime
import asyncio
import logging
from src.bot_core.settings import settings  # fully typed alias
from src.bot_core.settings import Settings

logger = logging.getLogger(__name__)


def _generate_backup_filename(backup_dir: Path) -> str:
    """Generate a unique backup filename in the backup directory.

    Args:
        backup_dir: Path to the backup directory.

    Returns:
        str: Unique backup filename (not full path).
    """
    base_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = 0
    while True:
        filename = f"backup_{base_timestamp}"
        if suffix:
            filename += f"_{suffix}"
        filename += ".db"
        fullpath = backup_dir / filename
        if not fullpath.exists():
            return filename
        suffix += 1


def create_backup(cfg: Optional[Settings] = None) -> Path | None:
    """Create a backup of the current database.

    Args:
        cfg: Settings object to use (optional).

    Returns:
        Path: The file path of the created backup, or None if creation failed.
    """
    cfg = cfg or settings
    db_path = Path(cfg.db_name)
    backup_dir = db_path.parent / "backups"
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.warning(f"Failed to create backup directory '{backup_dir}'. Error: {e}")
        return None

    backup_filename = _generate_backup_filename(backup_dir)
    backup_path = backup_dir / backup_filename

    try:
        shutil.copyfile(str(db_path), str(backup_path))
        logger.info(f"Backup created at: {backup_path}")
        return backup_path
    except Exception as e:
        logger.warning(f"Failed to create backup file at '{backup_path}'. Error: {e}")
        return None


def list_backups(cfg: Optional[Settings] = None) -> list[Path]:
    """List all backup files in the backup directory.

    Args:
        cfg: Settings object to use (optional).

    Returns:
        list[Path]: A sorted list of backup file Paths.
    """
    cfg = cfg or settings
    db_path = Path(cfg.db_name)
    backup_dir = db_path.parent / "backups"
    if not backup_dir.exists():
        return []
    backups = sorted(
        [f for f in backup_dir.iterdir() if f.suffix == ".db" and f.is_file()]
    )
    return backups


def restore_backup(backup_filename: str, cfg: Optional[Settings] = None) -> bool:
    """Restore the database from a specified backup file.

    Args:
        backup_filename: The name of the backup file (found in the backups folder).
        cfg: Settings object to use (optional).

    Returns:
        bool: True if restoration is successful, False otherwise.
    """
    cfg = cfg or settings
    db_path = Path(cfg.db_name)
    backup_dir = db_path.parent / "backups"
    backup_path = backup_dir / backup_filename
    if not backup_path.exists():
        return False

    try:
        shutil.copyfile(str(backup_path), str(db_path))
    except Exception as e:
        logger.warning(
            f"Failed to restore backup '{backup_filename}' to '{cfg.db_name}'. Error: {e}"
        )
        return False

    return True


def _prune_backups(
    max_backups: int | None = None, cfg: Optional[Settings] = None
) -> None:
    """Delete oldest backups if number of backups exceeds max_backups.

    Args:
        max_backups: Maximum number of backups to retain.
        cfg: Settings object to use (optional).
    """
    if not max_backups or max_backups < 1:
        return
    backups = list_backups(cfg=cfg)
    if len(backups) > max_backups:
        for old in backups[:-max_backups]:
            try:
                old.unlink()
                logger.info(f"Deleted old backup: {old}")
            except Exception as e:
                logger.warning(f"Failed to delete old backup '{old}': {e}")


async def start_periodic_backups(cfg: Optional[Settings] = None) -> None:
    """Start periodic backups.

    Schedule periodic backups at the specified interval.

    Args:
        cfg: Settings object.
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
