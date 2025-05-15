#!/usr/bin/env python
"""
db/repository.py
----------------
Unified repository code with helpers for database operations.
Now only includes user states.
"""

import sqlite3
import logging
from db.connection import get_connection

logger = logging.getLogger(__name__)

def execute_sql(query: str, params: tuple = (), commit: bool = False,
                fetchone: bool = False, fetchall: bool = False):
    """
    execute_sql - Execute a SQL query with optional commit/fetch.

    Args:
        query (str): The SQL to execute.
        params (tuple): Parameters for placeholders.
        commit (bool): Whether to commit after execute.
        fetchone (bool): Return a single row.
        fetchall (bool): Return all rows.

    Returns:
        The fetched row(s) if fetch flags are set, else None.
    """
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(query, params)
        if fetchone:
            result = cursor.fetchone()
        elif fetchall:
            result = cursor.fetchall()
        else:
            result = None
        if commit:
            conn.commit()
        return result
    except sqlite3.Error as e:
        logger.error(f"SQL error in execute_sql: {e} | Query: {query}")
        raise
    finally:
        if conn:
            conn.close()

class BaseRepository:
    def __init__(self, table_name: str, primary_key: str = "id",
                 connection_provider=get_connection, external_connection: bool = False):
        self.table_name = table_name
        self.primary_key = primary_key
        self.connection_provider = connection_provider
        self.external_connection = external_connection

    def _maybe_close(self, conn):
        if not self.external_connection:
            conn.close()

    def create(self, data: dict, replace: bool = False) -> int:
        operator = "INSERT OR REPLACE" if replace else "INSERT"
        columns = ", ".join(data.keys())
        placeholders = ", ".join(["?"] * len(data))
        query = f"{operator} INTO {self.table_name} ({columns}) VALUES ({placeholders})"
        params = tuple(data.values())
        conn = self.connection_provider()
        cursor = conn.cursor()
        cursor.execute(query, params)
        conn.commit()
        last_id = cursor.lastrowid
        self._maybe_close(conn)
        return last_id

    def get_by_id(self, id_value):
        query = f"SELECT * FROM {self.table_name} WHERE {self.primary_key} = ?"
        conn = self.connection_provider()
        cursor = conn.cursor()
        cursor.execute(query, (id_value,))
        row = cursor.fetchone()
        self._maybe_close(conn)
        return row

    def update(self, id_value, data: dict) -> None:
        fields = ", ".join([f"{key} = ?" for key in data.keys()])
        query = f"UPDATE {self.table_name} SET {fields} WHERE {self.primary_key} = ?"
        params = tuple(data.values()) + (id_value,)
        conn = self.connection_provider()
        cursor = conn.cursor()
        cursor.execute(query, params)
        conn.commit()
        self._maybe_close(conn)

    def delete(self, id_value) -> None:
        query = f"DELETE FROM {self.table_name} WHERE {self.primary_key} = ?"
        conn = self.connection_provider()
        cursor = conn.cursor()
        cursor.execute(query, (id_value,))
        conn.commit()
        self._maybe_close(conn)

    def list_all(self, filters: dict = None, order_by: str = None) -> list:
        query = f"SELECT * FROM {self.table_name}"
        params = ()
        if filters:
            conditions = " AND ".join([f"{k} = ?" for k in filters.keys()])
            query += f" WHERE {conditions}"
            params = tuple(filters.values())
        if order_by:
            query += f" ORDER BY {order_by}"
        conn = self.connection_provider()
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()
        self._maybe_close(conn)
        return rows or []

    def delete_by_conditions(self, conditions: dict) -> None:
        cond_str = " AND ".join([f"{key} = ?" for key in conditions.keys()])
        query = f"DELETE FROM {self.table_name} WHERE {cond_str}"
        params = tuple(conditions.values())
        conn = self.connection_provider()
        cursor = conn.cursor()
        cursor.execute(query, params)
        conn.commit()
        self._maybe_close(conn)

# --- UserStates Repository (for multi-step flows) ---

class UserStatesRepository(BaseRepository):
    """
    UserStatesRepository - Manages read/write of the UserStates table, keyed by user_id.
    The 'flow_state' column stores the JSON state.
    """
    def __init__(self, connection_provider=get_connection, external_connection=False):
        super().__init__("UserStates", primary_key="user_id",
                         connection_provider=connection_provider,
                         external_connection=external_connection)

# End of db/repository.py