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

from typing import Any, Dict, Optional, Tuple, List, Union
from collections.abc import Mapping

# from db.repository import BaseRepository  # Removed: use direct aiosqlite/SQLAlchemy queries instead
from bot_core.storage import acquire
import aiosqlite  # Ensure this is imported


async def fetch_one(
    query: str, params: Tuple[Any, ...] = ()
) -> Optional[Dict[str, Any]]:
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
    if isinstance(row, Mapping):
        return dict(row)
    # If row is a tuple, try to get column names from cursor description (handled in _execute_sql_async)
    if isinstance(row, dict):
        return row
    # Fallback: not dict-like
    raise TypeError("fetch_one: Row is not dict-like; check DB row_factory or query.")


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
    if not isinstance(rows, list):
        raise TypeError("fetch_all: Expected list result from _execute_sql_async.")
    if not rows:
        return []
    if not all(isinstance(r, Mapping) for r in rows):
        raise TypeError(
            "fetch_all: Row is not dict-like; check DB row_factory or query."
        )
    return [dict(r) for r in rows]


async def execute_query(
    query: str, params: Tuple[Any, ...] = (), commit: bool = False
) -> None:
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
    Raises ValueError if data is empty. Raises RuntimeError on DB error.

    Note: If the table does not have an AUTOINCREMENT primary key, this will return 0.

    Usage Example:
        from bot_core.api.db_api import insert_record

        new_id = await insert_record("Volunteers", {"phone": "+15551234567", "name": "Alice"}, replace=False)
        print("Inserted row with ID =", new_id)
    """
    if not data:
        raise ValueError("No data provided for insert_record.")
    cols = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    verb = "INSERT OR REPLACE" if replace else "INSERT"
    sql = f"{verb} INTO {table} ({cols}) VALUES ({placeholders})"
    params = tuple(data.values())
    try:
        async with acquire() as conn:
            cursor = await conn.execute(sql, params)
            await conn.commit()
            lastrowid = cursor.lastrowid or 0
            return lastrowid
    except Exception as e:
        raise RuntimeError(f"Failed to insert record into {table}: {e}") from e


async def _execute_sql_async(
    query: str,
    params: Tuple[Any, ...] = (),
    commit: bool = False,
    fetchone: bool = False,
    fetchall: bool = False,
) -> Union[None, Dict[str, Any], List[Dict[str, Any]]]:
    async with acquire() as conn:
        # Ensure rows are returned as dict-like objects
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(query, params)
        if fetchone:
            row_result = await cursor.fetchone()
            if commit:
                await conn.commit()
            if hasattr(cursor, "description") and cursor.description is not None:
                result_cursor_desc = [desc[0] for desc in cursor.description]
                if row_result is not None and not hasattr(row_result, "keys"):
                    return dict(zip(result_cursor_desc, row_result))
            if row_result is None:
                return None
            # aiosqlite.Row → plain dict
            if hasattr(row_result, "keys"):
                return {k: row_result[k] for k in row_result.keys()}
            if isinstance(row_result, Mapping):
                return dict(row_result)
            raise TypeError("_execute_sql_async: Unexpected result type for fetchone.")
        elif fetchall:
            rows_result = await cursor.fetchall()
            rows_result = list(rows_result)
            if commit:
                await conn.commit()
            if hasattr(cursor, "description") and cursor.description is not None:
                result_cursor_desc = [desc[0] for desc in cursor.description]
                if rows_result and not hasattr(rows_result[0], "keys"):
                    return [dict(zip(result_cursor_desc, r)) for r in rows_result]
            if not isinstance(rows_result, list):
                raise TypeError(
                    "_execute_sql_async: Expected list result for fetchall."
                )
            if not rows_result:
                return []
            if not all(isinstance(r, Mapping) for r in rows_result):
                raise TypeError(
                    "_execute_sql_async: Row is not dict-like; check DB row_factory or query."
                )
            return [dict(r) for r in rows_result]
        else:
            if commit:
                await conn.commit()
            return None


# End of core/api/db_api.py
