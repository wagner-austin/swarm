#!/usr/bin/env python
"""
core/transaction.py - Provides a context manager for atomic DB transactions.
Ensures critical writes use SQLite's transaction locking.
Changes:
 - Added an 'exclusive' parameter. If True, uses BEGIN EXCLUSIVE to force serialization.
"""
from contextlib import contextmanager
from db.connection import get_connection

@contextmanager
def atomic_transaction(exclusive: bool = False):
    """
    atomic_transaction - Context manager that provides a database connection with an atomic transaction.
    
    Args:
        exclusive (bool): If True, starts an exclusive transaction (BEGIN EXCLUSIVE) to block all concurrent access.
                         Otherwise, uses BEGIN IMMEDIATE.
    
    Yields:
        A SQLite connection with an active transaction.
    """
    conn = get_connection()
    try:
        if exclusive:
            conn.execute("BEGIN EXCLUSIVE")
        else:
            conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

# End of core/transaction.py