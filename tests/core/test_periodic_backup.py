#!/usr/bin/env python
"""
tests/core/test_periodic_backup.py --- Tests for periodic backup scheduling and stress tests.
Verifies that the periodic backup function creates backups at defined intervals, handles errors gracefully,
and that the cleanup logic efficiently manages a very large number of backups.
"""

import asyncio
import os
import shutil
import time
import pytest
from tests.async_helpers import override_async_sleep
from db.backup import start_periodic_backups, list_backups, cleanup_backups, BACKUP_DIR

@pytest.mark.asyncio
async def test_periodic_backup_once(monkeypatch):
    try:
        if os.path.exists(BACKUP_DIR):
            shutil.rmtree(BACKUP_DIR)
        
        async with override_async_sleep(monkeypatch, scale=0.01):
            task = asyncio.create_task(start_periodic_backups(interval_seconds=0.1, max_backups=10))
            
            start_time = time.time()
            timeout = 0.5
            backups = []
            while time.time() - start_time < timeout:
                backups = list_backups()
                if backups:
                    break
                await asyncio.sleep(0.01)
            
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        assert len(backups) >= 1, "No backups were created within the timeout period."
    finally:
        if os.path.exists(BACKUP_DIR):
            shutil.rmtree(BACKUP_DIR)

@pytest.mark.asyncio
async def test_periodic_backup_error_handling(monkeypatch, caplog):
    """
    Test that a failure in create_backup during periodic backups is handled gracefully,
    logs a warning, and does not kill the backup task.
    """
    from db.backup import create_backup as original_create_backup
    call_count = 0

    def failing_create_backup():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise OSError("Simulated failure during backup creation")
        return original_create_backup()

    monkeypatch.setattr("db.backup.create_backup", failing_create_backup)

    try:
        async with override_async_sleep(monkeypatch, scale=0.01):
            task = asyncio.create_task(start_periodic_backups(interval_seconds=0.1, max_backups=10))
            await asyncio.sleep(0.3)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    finally:
        monkeypatch.undo()

    warnings = [record.message for record in caplog.records if "Periodic backup failed" in record.message]
    assert warnings, "Expected a warning log entry for backup failure."

def test_cleanup_large_number_of_backups():
    """
    Test cleanup_backups with a very large number of backup files to ensure efficiency and correctness.
    """
    try:
        if os.path.exists(BACKUP_DIR):
            shutil.rmtree(BACKUP_DIR)
        os.makedirs(BACKUP_DIR)
        # Create 100 dummy backup files
        for i in range(100):
            filename = f"backup_large_{i:03}.db"
            filepath = os.path.join(BACKUP_DIR, filename)
            with open(filepath, "w") as f:
                f.write("dummy content")
        cleanup_backups(max_backups=5)
        backups = list_backups()
        assert len(backups) == 5, f"Expected 5 backups after cleanup, got {len(backups)}"
    finally:
        if os.path.exists(BACKUP_DIR):
            shutil.rmtree(BACKUP_DIR)

# End of tests/core/test_periodic_backup.py