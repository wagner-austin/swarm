"""
tests/core/test_database_connection.py - Tests for the database connection module.
Verifies that get_connection returns a valid SQLite connection, and handles errors properly.
"""

import sqlite3
import pytest
from unittest.mock import patch
import logging
from db.connection import get_connection

def test_get_connection():
    conn = get_connection()
    assert isinstance(conn, sqlite3.Connection)
    # Check that the row_factory is set to sqlite3.Row
    assert conn.row_factory == sqlite3.Row
    conn.close()

@pytest.mark.parametrize("error_class", [sqlite3.OperationalError, OSError])
def test_get_connection_raises_and_logs(error_class, caplog):
    """
    test_get_connection_raises_and_logs - Simulate an unusual DB connection failure
    (e.g., sqlite3.OperationalError or OSError). Confirm we log an error and re-raise.
    """
    with patch("sqlite3.connect", side_effect=error_class("Simulated DB error")):
        with pytest.raises(error_class):
            with caplog.at_level(logging.ERROR):
                get_connection()
        # Confirm we logged an error message
        assert any("Error connecting to SQLite database" in rec.message for rec in caplog.records)

# End of tests/core/test_database_connection.py