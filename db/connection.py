#!/usr/bin/env python
"""
db/connection.py - Provides database connection functions.
Establishes and returns a connection to the SQLite database and includes a context manager for automatic handling.
"""

import sqlite3
import logging
from sqlite3 import Connection
from contextlib import contextmanager
from bot_core.config import DB_NAME

logger = logging.getLogger(__name__)

def get_connection() -> Connection:
    """
    get_connection - Establish and return a connection to the SQLite database.
    
    This function now includes basic error handling for OperationalError or OSError.
    Logs an error and then re-raises the exception if encountered.

    Returns:
        Connection: The SQLite connection object with row_factory set to sqlite3.Row.
    """
    try:
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        return conn
    except (sqlite3.OperationalError, OSError) as e:
        logger.error(f"Error connecting to SQLite database {DB_NAME!r}: {e}")
        raise
    except Exception as ex:
        # Catch-all for unexpected exceptions
        logger.error(f"Unexpected error while connecting to SQLite database {DB_NAME!r}: {ex}")
        raise

@contextmanager
def db_connection():
    """
    db_connection - Context manager for SQLite database connection.
    
    Yields:
        Connection: The SQLite connection object with row_factory set.
    Ensures that the connection is closed after usage.
    """
    conn = None
    try:
        conn = get_connection()
        yield conn
    finally:
        if conn:
            conn.close()

# End of db/connection.py