#!/usr/bin/env python
"""
tests/core/test_database_backup.py - Tests for database backup and restore functionality.
Verifies that backups are created, listed, cleaned up per retention policy, that restore functionality works,
and now ensures that multiple backups in the same second do not produce filename collisions.
Changes:
 - Added tests to simulate failure conditions:
    - Patching shutil.copyfile to raise an IOError mid-copy.
    - Restoring from a truncated backup file (only 16 bytes long).
"""

import os
import shutil
import pytest
import logging
from unittest.mock import patch
from db.backup import (
    create_backup, list_backups, cleanup_backups,
    restore_backup, BACKUP_DIR
)
from db.connection import get_connection

def test_create_backup(caplog):
    # Ensure no backups initially
    if os.path.exists(BACKUP_DIR):
        shutil.rmtree(BACKUP_DIR)
    try:
        with caplog.at_level(logging.INFO):
            backup_path = create_backup()
        # The creation may return an empty string if it failed
        assert backup_path != "", "Expected a valid backup path string."
        assert os.path.exists(backup_path)
        backups = list_backups()
        assert len(backups) == 1
        # Assert that an info-level log about backup creation is present
        assert any("Backup created at:" in rec.message for rec in caplog.records), (
            "Expected an info-level log about successful backup creation."
        )
    finally:
        if os.path.exists(BACKUP_DIR):
            shutil.rmtree(BACKUP_DIR)

def test_cleanup_backups():
    try:
        # Create 12 dummy backup files manually
        if os.path.exists(BACKUP_DIR):
            shutil.rmtree(BACKUP_DIR)
        os.makedirs(BACKUP_DIR)
        for i in range(12):
            filename = f"backup_20210101_00000{i}.db"
            filepath = os.path.join(BACKUP_DIR, filename)
            with open(filepath, "w") as f:
                f.write("dummy")
        cleanup_backups(max_backups=10)
        backups = list_backups()
        assert len(backups) == 10
        # Check that the oldest backup is removed
        assert "backup_20210101_000000.db" not in backups
    finally:
        if os.path.exists(BACKUP_DIR):
            shutil.rmtree(BACKUP_DIR)

def test_restore_backup():
    try:
        # Initialize a valid SQLite database with known content.
        conn = get_connection()
        cursor = conn.cursor()
        # Create a test table and insert a known row.
        cursor.execute("CREATE TABLE IF NOT EXISTS TestData (id INTEGER PRIMARY KEY, value TEXT)")
        cursor.execute("DELETE FROM TestData")  # Ensure clean table
        cursor.execute("INSERT INTO TestData (value) VALUES (?)", ("original",))
        conn.commit()
        conn.close()

        # Create a backup of the valid database.
        backup_path = create_backup()
        backup_filename = backup_path.split(os.sep)[-1]

        # Modify the database using SQL (update the row).
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE TestData SET value = ? WHERE id = 1", ("modified",))
        conn.commit()
        conn.close()

        # Verify that the data has been modified.
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM TestData WHERE id = 1")
        row = cursor.fetchone()
        conn.close()
        assert row is not None and row["value"] == "modified"

        # Restore the database from the backup.
        result = restore_backup(backup_filename)
        assert result is True

        # Verify that the data is reverted to the original state.
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM TestData WHERE id = 1")
        row = cursor.fetchone()
        conn.close()
        assert row is not None and row["value"] == "original"
    finally:
        if os.path.exists(BACKUP_DIR):
            shutil.rmtree(BACKUP_DIR)

@pytest.mark.parametrize("retention_value", [0, -1])
def test_cleanup_backups_zero_or_negative_retention(retention_value):
    """
    Ensures that when max_backups <= 0, the function removes all backups.
    Also checks that a warning is logged if retention_value is zero or negative.
    """
    try:
        # Clean up the backup folder first
        if os.path.exists(BACKUP_DIR):
            shutil.rmtree(BACKUP_DIR)
        os.makedirs(BACKUP_DIR)

        # Create some dummy backups
        for i in range(5):
            filename = f"edgecase_backup_{i}.db"
            with open(os.path.join(BACKUP_DIR, filename), "w") as f:
                f.write("dummy content")

        # Confirm 5 backups are present
        initial_backups = list_backups()
        assert len(initial_backups) == 5

        with patch("db.backup.logger.warning") as mock_logger:
            cleanup_backups(max_backups=retention_value)

        # After cleanup, should have zero backups left
        final_backups = list_backups()
        assert len(final_backups) == 0, (
            f"Expected no backups left for max_backups={retention_value}, found {final_backups}."
        )

        # Check that a warning was logged for negative or zero
        if retention_value <= 0:
            mock_logger.assert_called_once()
            call_args, _ = mock_logger.call_args
            assert "removing all backups" in call_args[0].lower()
    finally:
        if os.path.exists(BACKUP_DIR):
            shutil.rmtree(BACKUP_DIR)

@pytest.mark.parametrize("os_error", [OSError("Test OSError")])
def test_create_backup_makedirs_failure(os_error):
    """
    Test that when os.makedirs() fails with an OSError, create_backup() handles it gracefully.
    """
    if os.path.exists(BACKUP_DIR):
        shutil.rmtree(BACKUP_DIR)
    with patch("os.makedirs", side_effect=os_error):
        backup_path = create_backup()
        # Expect an empty string to signal the backup was skipped or failed gracefully.
        assert backup_path == "", "create_backup should return an empty string on directory creation failure."
    assert not os.path.exists(BACKUP_DIR), "Backup directory should not exist after a forced failure."

def test_restore_corrupted_backup():
    """
    Test that restoring from a zero-byte or otherwise invalid backup file returns False
    and logs a warning about an invalid or corrupted file.
    """
    try:
        if os.path.exists(BACKUP_DIR):
            shutil.rmtree(BACKUP_DIR)
        os.makedirs(BACKUP_DIR)

        # Create a zero-byte backup file
        corrupted_filename = "corrupted_backup.db"
        corrupted_path = os.path.join(BACKUP_DIR, corrupted_filename)
        with open(corrupted_path, "wb"):
            pass  # zero bytes

        with patch("db.backup.logger.warning") as mock_warning:
            result = restore_backup(corrupted_filename)

        assert result is False, "Expected restore_backup to return False for corrupted DB file."
        mock_warning.assert_called_once()
        call_args, _ = mock_warning.call_args
        assert "invalid or corrupted" in call_args[0].lower()
    finally:
        if os.path.exists(BACKUP_DIR):
            shutil.rmtree(BACKUP_DIR)

def test_create_backup_copyfile_failure():
    """
    Test that if shutil.copyfile raises an IOError, create_backup() logs a warning and returns an empty string.
    """
    try:
        if os.path.exists(BACKUP_DIR):
            shutil.rmtree(BACKUP_DIR)
        os.makedirs(BACKUP_DIR)
        with patch("shutil.copyfile", side_effect=IOError("Simulated IOError")):
            with patch("db.backup.logger.warning") as mock_logger:
                backup_path = create_backup()
                assert backup_path == "", "Expected create_backup to return an empty string on IOError during copyfile."
                mock_logger.assert_called()
    finally:
        if os.path.exists(BACKUP_DIR):
            shutil.rmtree(BACKUP_DIR)

def test_restore_truncated_backup():
    """
    Test that restoring from a backup file that is exactly 16 bytes (i.e. truncated)
    logs a warning and returns False.
    """
    try:
        if os.path.exists(BACKUP_DIR):
            shutil.rmtree(BACKUP_DIR)
        os.makedirs(BACKUP_DIR)
        truncated_filename = "truncated_backup.db"
        truncated_path = os.path.join(BACKUP_DIR, truncated_filename)
        # Write exactly 16 bytes matching the SQLite header.
        with open(truncated_path, "wb") as f:
            f.write(b"SQLite format 3\000")
        with patch("db.backup.logger.warning") as mock_logger:
            result = restore_backup(truncated_filename)
            assert result is False, "Expected restore_backup to return False for a truncated backup file."
            mock_logger.assert_called_once()
            call_args, _ = mock_logger.call_args
            assert "invalid or corrupted" in call_args[0].lower()
    finally:
        if os.path.exists(BACKUP_DIR):
            shutil.rmtree(BACKUP_DIR)

def test_frequent_backups_same_second():
    """
    Ensures that multiple create_backup calls in the same second do not collide on filename generation.
    We expect each call to produce a unique .db file in BACKUP_DIR.
    """
    try:
        if os.path.exists(BACKUP_DIR):
            shutil.rmtree(BACKUP_DIR)
        os.makedirs(BACKUP_DIR)

        created_paths = []
        for _ in range(5):
            path = create_backup()
            assert path, "Expected a valid backup path."
            created_paths.append(path)

        backups = list_backups()
        assert len(backups) == 5, f"Expected 5 distinct backups in the same second, found: {backups}"
        created_filenames = set(os.path.basename(p) for p in created_paths)
        backups_set = set(backups)
        assert created_filenames == backups_set, "The created backup filenames do not match the files in the directory."
    finally:
        if os.path.exists(BACKUP_DIR):
            shutil.rmtree(BACKUP_DIR)

# End of tests/core/test_database_backup.py