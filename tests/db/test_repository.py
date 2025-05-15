#!/usr/bin/env python
"""
tests/db/test_repository.py - Tests for db.repository module
-----------------------------------------------------------
Ensures that execute_sql and BaseRepository methods work as expected,
including fetchone/fetchall usage and basic CRUD operations.
"""

import pytest
from bot_core.api import db_api


@pytest.mark.asyncio
async def test_execute_sql_fetchone(async_db):
    """
    Ensure async DB API can fetch exactly one row with fetch_one.
    """
    # Create a temporary table and insert a record using async DB API
    await db_api.execute_query("CREATE TABLE IF NOT EXISTS TestTable (id INTEGER PRIMARY KEY, value TEXT)", commit=True)
    await db_api.execute_query("DELETE FROM TestTable", commit=True)
    await db_api.execute_query("INSERT INTO TestTable (value) VALUES (?)", ("test_value",), commit=True)

    row = await db_api.fetch_one("SELECT value FROM TestTable WHERE id = ?", (1,))
    assert row is not None
    assert row["value"] == "test_value"


@pytest.mark.asyncio
async def test_execute_sql_fetchall(async_db):
    """
    Ensure async DB API can fetch multiple rows with fetch_all.
    """
    await db_api.execute_query("CREATE TABLE IF NOT EXISTS TestTable (id INTEGER PRIMARY KEY, value TEXT)", commit=True)
    await db_api.execute_query("DELETE FROM TestTable", commit=True)
    for val in ["val1", "val2", "val3"]:
        await db_api.execute_query("INSERT INTO TestTable (value) VALUES (?)", (val,), commit=True)

    rows = await db_api.fetch_all("SELECT value FROM TestTable")
    assert len(rows) == 3
    values = [row["value"] for row in rows]
    assert "val1" in values and "val2" in values and "val3" in values

# End of tests/db/test_repository.py