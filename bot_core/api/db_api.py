"""
core/api/db_api.py
------------------
Stable DB Access API for plugin and manager developers.
Provides minimal, well-documented functions for CRUD operations and raw queries,
wrapping the lower-level repository or connection logic.

Usage Example:
    from bot_core.api.db_api import fetch_one, insert_record

    row = fetch_one("SELECT * FROM Volunteers WHERE phone=?", (phone,))
    insert_record("Volunteers", {"phone": phone, "name": "Alice"})
"""

from typing import Any, Dict, Optional, Tuple, List
from db.repository import BaseRepository
from bot_core.storage import acquire
import aiosqlite  # Ensure this is imported

async def fetch_one(query: str, params: Tuple[Any, ...] = ()) -> Optional[Dict[str, Any]]:
    """
    fetch_one(query, params=()) -> dict or None
    -------------------------------------------
    Execute the query with given params and return the first row as a dictionary, or None if no rows.

    Usage Example:
        from bot_core.api.db_api import fetch_one

        row = await fetch_one("SELECT * FROM Volunteers WHERE phone=?", ("+15551234567",))
        if row:
            print("Found volunteer:", row["phone"])
    """
    row = await _execute_sql_async(query, params, fetchone=True)
    if row is None:
        return None
    # If row is already dict-like
    if hasattr(row, 'keys'):
        return {col: row[col] for col in row.keys()}
    # If row is a tuple, try to get column names from cursor description (handled in _execute_sql_async)
    if isinstance(row, dict):
        return row
    # Fallback: enumerate
    return dict(enumerate(row))

async def fetch_all(query: str, params: Tuple[Any, ...] = ()) -> List[Dict[str, Any]]:
    """
    fetch_all(query, params=()) -> list of dict
    -------------------------------------------
    Execute the query and return all matching rows as a list of dictionaries, or an empty list if no rows.

    Usage Example:
        from bot_core.api.db_api import fetch_all

        rows = await fetch_all("SELECT * FROM Volunteers WHERE available=?", (1,))
        for row in rows:
            print("Available volunteer:", row["phone"])
    """
    rows = await _execute_sql_async(query, params, fetchall=True)
    if not rows:
        return []
    if hasattr(rows[0], 'keys'):
        return [{col: r[col] for col in r.keys()} for r in rows]
    if isinstance(rows[0], dict):
        return rows
    # Fallback: enumerate
    return [dict(enumerate(r)) for r in rows]

async def execute_query(query: str, params: Tuple[Any, ...] = (), commit: bool = False) -> None:
    """
    execute_query(query, params=(), commit=False) -> None
    -----------------------------------------------------
    Execute a SQL statement (INSERT, UPDATE, DELETE, or arbitrary).
    If commit=True, commits the transaction.

    Usage Example:
        from bot_core.api.db_api import execute_query

        await execute_query("UPDATE Volunteers SET available=? WHERE phone=?", (0, "+15551234567"), commit=True)
    """
    await _execute_sql_async(query, params, commit=commit)

async def insert_record(table: str, data: Dict[str, Any], replace: bool = False) -> int:
    """
    insert_record(table, data, replace=False) -> int
    ------------------------------------------------
    Insert a new row into the given table and return the newly inserted row's ID if available.
    If replace=True, uses 'INSERT OR REPLACE'.

    Usage Example:
        from bot_core.api.db_api import insert_record

        new_id = await insert_record("Volunteers", {"phone": "+15551234567", "name": "Alice"}, replace=False)
        print("Inserted row with ID =", new_id)
    """
    repo = BaseRepository(table_name=table)
    return await repo.create(data, replace=replace)

async def _execute_sql_async(query: str, params: Tuple[Any, ...] = (), commit: bool = False, fetchone: bool = False, fetchall: bool = False):
    async with acquire() as conn:
        # Ensure rows are returned as dict-like objects
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(query, params)
        result = None
        if fetchone:
            result = await cursor.fetchone()
        elif fetchall:
            result = await cursor.fetchall()
        if commit:
            await conn.commit()
        # Attach cursor description for fallback dict conversion
        if hasattr(cursor, 'description') and cursor.description is not None:
            result_cursor_desc = [desc[0] for desc in cursor.description]
            if fetchone and result is not None and not hasattr(result, 'keys'):
                # Convert tuple row to dict using description
                result = dict(zip(result_cursor_desc, result))
            elif fetchall and result and not hasattr(result[0], 'keys'):
                result = [dict(zip(result_cursor_desc, r)) for r in result]
        return result

# End of core/api/db_api.py