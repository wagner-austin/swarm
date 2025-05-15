#!/usr/bin/env python
"""
tests/db/test_repository.py - Tests for db.repository module
-----------------------------------------------------------
Ensures that execute_sql and BaseRepository methods work as expected,
including fetchone/fetchall usage and basic CRUD operations.
"""

from db.connection import db_connection
from db.repository import execute_sql


def test_execute_sql_fetchone():
    """
    Ensure execute_sql can fetch exactly one row with fetchone=True.
    """
    # Create a temporary table and insert a record.
    with db_connection() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS TestTable (id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("DELETE FROM TestTable")  # Clear table
        conn.execute("INSERT INTO TestTable (value) VALUES (?)", ("test_value",))
        conn.commit()

    result = execute_sql("SELECT value FROM TestTable WHERE id = ?", (1,), fetchone=True)
    assert result is not None
    assert result["value"] == "test_value"


def test_execute_sql_fetchall():
    """
    Ensure execute_sql can fetch multiple rows with fetchall=True.
    """
    with db_connection() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS TestTable (id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("DELETE FROM TestTable")  # Clear table
        conn.executemany("INSERT INTO TestTable (value) VALUES (?)", [("val1",), ("val2",), ("val3",)])
        conn.commit()

    results = execute_sql("SELECT value FROM TestTable", fetchall=True)
    assert len(results) == 3
    values = [row["value"] for row in results]
    assert "val1" in values and "val2" in values and "val3" in values

# End of tests/db/test_repository.py