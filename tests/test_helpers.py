#!/usr/bin/env python
"""
tests/test_helpers.py - Consolidated helper functions for database operations in tests.
This module provides common functions for inserting test records, fetching results, and cleaning up tables.
All tests requiring database operations should import these functions to avoid code duplication and ensure consistency.
"""

from bot_core.storage import acquire
import pytest

@pytest.mark.asyncio
async def insert_record(query, params):
    """
    insert_record - Inserts a record using the provided SQL query and parameters.
    
    Args:
        query (str): The SQL query to execute.
        params (tuple): Parameters for the SQL query.
        
    Returns:
        int: The last inserted row id.
    """
    async with acquire() as conn:
        cursor = await conn.execute(query, params)
        await conn.commit()
        last_id = cursor.lastrowid
        return last_id

@pytest.mark.asyncio
async def fetch_one(query, params=()):
    """
    fetch_one - Executes a SQL query and returns a single result.
    
    Args:
        query (str): The SQL query to execute.
        params (tuple, optional): Parameters for the SQL query.
        
    Returns:
        sqlite3.Row: The first row of the result set.
    """
    async with acquire() as conn:
        cursor = await conn.execute(query, params)
        row = await cursor.fetchone()
        return row

@pytest.mark.asyncio
async def cleanup_table(table_name):
    """
    cleanup_table - Deletes all records from the specified table.
    
    Args:
        table_name (str): Name of the table to clean.
    """
    async with acquire() as conn:
        await conn.execute(f"DELETE FROM {table_name}")
        await conn.commit()

# End of tests/test_helpers.py