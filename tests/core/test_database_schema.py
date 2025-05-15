#!/usr/bin/env python
"""
tests/core/test_database_schema.py - Tests for the database schema module.
Verifies that init_db creates the necessary table: SchemaVersion.
"""

from db.schema import init_db
from db.connection import get_connection

def test_init_db_creates_tables():
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    # Check for the SchemaVersion table only
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='SchemaVersion'")
    assert cursor.fetchone() is not None, "SchemaVersion table not created."

    conn.close()

# End of tests/core/test_database_schema.py