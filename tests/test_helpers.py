#!/usr/bin/env python
"""
tests/test_helpers.py - Consolidated helper functions for database operations in tests.
This module provides common functions for inserting test records, fetching results, and cleaning up tables.
All tests requiring database operations should import these functions to avoid code duplication and ensure consistency.
"""

from db.connection import get_connection

def insert_record(query, params):
    """
    insert_record - Inserts a record using the provided SQL query and parameters.
    
    Args:
        query (str): The SQL query to execute.
        params (tuple): Parameters for the SQL query.
        
    Returns:
        int: The last inserted row id.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(query, params)
    conn.commit()
    last_id = cursor.lastrowid
    conn.close()
    return last_id

def fetch_one(query, params=()):
    """
    fetch_one - Executes a SQL query and returns a single result.
    
    Args:
        query (str): The SQL query to execute.
        params (tuple, optional): Parameters for the SQL query.
        
    Returns:
        sqlite3.Row: The first row of the result set.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(query, params)
    row = cursor.fetchone()
    conn.close()
    return row

def cleanup_table(table_name):
    """
    cleanup_table - Deletes all records from the specified table.
    
    Args:
        table_name (str): Name of the table to clean.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(f"DELETE FROM {table_name}")
    conn.commit()
    conn.close()

# End of tests/test_helpers.py