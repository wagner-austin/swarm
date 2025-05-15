import os
import tempfile
import shutil
import pytest
from bot_core.settings import Settings
from db.backup import create_backup, list_backups


def test_create_backup_happy_path():
    # Create a temp directory for the test DB and backups
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, "test.db")
        # Write a dummy SQLite file
        with open(db_path, "wb") as f:
            f.write(b"SQLite format 3\x00dummy data\n")
        # Create a Settings instance pointing to this DB
        cfg = Settings(db_name=db_path)
        # Run the backup
        backup_path = create_backup(cfg)
        assert backup_path, "Backup path should not be empty"
        assert os.path.isfile(backup_path), f"Backup file should exist: {backup_path}"
        # It should appear in list_backups
        backups = list_backups(cfg)
        assert any(os.path.basename(backup_path) == b for b in backups), "Backup should be listed by list_backups()"
        # Optionally: check backup file content matches (not strictly required)
        with open(backup_path, "rb") as f:
            data = f.read()
        assert b"SQLite format 3" in data, "Backup file should contain SQLite header"
