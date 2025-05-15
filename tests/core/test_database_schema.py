#!/usr/bin/env python
"""
tests/core/test_database_schema.py - Tests for the database schema module.
Verifies that init_db creates the necessary tables: Volunteers, DeletedVolunteers, and UserStates.
"""

from db.schema import init_db
from db.connection import get_connection

def test_init_db_creates_tables():
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    # Check for the Volunteers table
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Volunteers'")
    assert cursor.fetchone() is not None, "Volunteers table not created."

    # Removed CommandLogs table check as it's no longer part of the schema.

    # Check for the DeletedVolunteers table
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='DeletedVolunteers'")
    assert cursor.fetchone() is not None, "DeletedVolunteers table not created."
    
    # Check for the UserStates table
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='UserStates'")
    assert cursor.fetchone() is not None, "UserStates table not created."
    
    conn.close()

# End of tests/core/test_database_schema.py