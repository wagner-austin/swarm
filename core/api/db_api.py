"""
core/api/db_api.py
------------------
Stable DB Access API for plugin and manager developers.
Provides minimal, well-documented functions for CRUD operations and raw queries,
wrapping the lower-level repository or connection logic.

Usage Example:
    from core.api.db_api import fetch_one, insert_record

    row = fetch_one("SELECT * FROM Volunteers WHERE phone=?", (phone,))
    insert_record("Volunteers", {"phone": phone, "name": "Alice"})
"""

from typing import Any, Dict, Optional, Tuple, List
from db.repository import execute_sql

def fetch_one(query: str, params: Tuple[Any, ...] = ()) -> Optional[Dict[str, Any]]:
    """
    fetch_one(query, params=()) -> dict or None
    -------------------------------------------
    Execute the query with given params and return the first row as a dictionary, or None if no rows.

    Usage Example:
        from core.api.db_api import fetch_one

        row = fetch_one("SELECT * FROM Volunteers WHERE phone=?", ("+15551234567",))
        if row:
            print("Found volunteer:", row["phone"])
    """
    row = execute_sql(query, params, fetchone=True)
    return dict(row) if row else None

def fetch_all(query: str, params: Tuple[Any, ...] = ()) -> List[Dict[str, Any]]:
    """
    fetch_all(query, params=()) -> list of dict
    -------------------------------------------
    Execute the query and return all matching rows as a list of dictionaries, or an empty list if no rows.

    Usage Example:
        from core.api.db_api import fetch_all

        rows = fetch_all("SELECT * FROM Volunteers WHERE available=?", (1,))
        for row in rows:
            print("Available volunteer:", row["phone"])
    """
    rows = execute_sql(query, params, fetchall=True)
    return [dict(r) for r in rows] if rows else []

def execute_query(query: str, params: Tuple[Any, ...] = (), commit: bool = False) -> None:
    """
    execute_query(query, params=(), commit=False) -> None
    -----------------------------------------------------
    Execute a SQL statement (INSERT, UPDATE, DELETE, or arbitrary).
    If commit=True, commits the transaction.

    Usage Example:
        from core.api.db_api import execute_query

        execute_query("UPDATE Volunteers SET available=? WHERE phone=?", (0, "+15551234567"), commit=True)
    """
    execute_sql(query, params, commit=commit)

def insert_record(table: str, data: Dict[str, Any], replace: bool = False) -> int:
    """
    insert_record(table, data, replace=False) -> int
    ------------------------------------------------
    Insert a new row into the given table and return the newly inserted row's ID if available.
    If replace=True, uses 'INSERT OR REPLACE'.

    Usage Example:
        from core.api.db_api import insert_record

        new_id = insert_record("Volunteers", {"phone": "+15551234567", "name": "Alice"}, replace=False)
        print("Inserted row with ID =", new_id)
    """
    from db.repository import BaseRepository
    repo = BaseRepository(table_name=table)
    return repo.create(data, replace=replace)

# End of core/api/db_api.py