#!/usr/bin/env python
"""
tests/core/test_database_migrations.py - Tests for database migrations.
Verifies that running migrations creates the necessary tables (Volunteers, DeletedVolunteers, UserStates, SchemaVersion),
updates the schema version, and ensures that the DeletedVolunteers table has the unified 'role' column.
Also tests that if the DB schema version is higher than the code's MIGRATIONS,
we skip migrations without crashing or downgrading.
"""

import pytest
import logging
from db.migrations import (
    get_current_version,
    run_migrations,
    MIGRATIONS,
    update_version
)
from db.connection import get_connection

@pytest.fixture(autouse=True)
def reset_schema(monkeypatch):
    """
    Reset the SchemaVersion table before each test by removing it if exists.
    This fixture ensures tests start from a known state.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS SchemaVersion")
    conn.commit()
    conn.close()
    yield

def test_get_current_version_initial():
    # Since SchemaVersion table was dropped, get_current_version should create it and return 0.
    version = get_current_version()
    assert version == 0

def test_run_migrations_creates_tables_and_updates_version():
    # Run migrations; this should create tables from all migrations.
    run_migrations()
    # After running migrations, schema version should equal the highest migration version.
    expected_version = max(version for version, _ in MIGRATIONS)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT version FROM SchemaVersion")
    row = cursor.fetchone()
    conn.close()
    assert row is not None
    assert row["version"] == expected_version

    # Check that expected tables exist.
    conn = get_connection()
    cursor = conn.cursor()
    expected_tables = {"Volunteers", "DeletedVolunteers", "UserStates", "SchemaVersion"}
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = set(row["name"] for row in cursor.fetchall())
    conn.close()
    for table in expected_tables:
        assert table in tables, f"Expected table {table} not found."

def test_deleted_volunteers_has_role_column():
    """
    Test that the DeletedVolunteers table has a 'role' column after migrations.
    """
    run_migrations()  # Ensure migrations are applied
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(DeletedVolunteers)")
    columns = [row["name"] for row in cursor.fetchall()]
    conn.close()
    assert "role" in columns, "DeletedVolunteers table should have a 'role' column."

def test_run_migrations_when_schema_version_exceeds_known(caplog):
    """
    test_run_migrations_when_schema_version_exceeds_known - Simulate
    an environment where the DB version is higher than the code’s known MIGRATIONS.
    We set SchemaVersion to a higher number, then call run_migrations() and verify
    we skip migrations and log a warning.
    """
    # Set schema version to something bigger than any known migration.
    large_version = max(v for v, _ in MIGRATIONS) + 10
    update_version(large_version)
    assert get_current_version() == large_version

    with caplog.at_level(logging.WARNING):
        run_migrations()

    # Confirm the version is unchanged.
    assert get_current_version() == large_version

    # Confirm we logged a warning about skipping migrations.
    assert any("Skipping migrations to prevent downgrade" in rec.message for rec in caplog.records)

# End of tests/core/test_database_migrations.py