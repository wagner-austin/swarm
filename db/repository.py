#!/usr/bin/env python
"""
db/repository.py
----------------
Unified repository code with helpers for database operations.
Now only includes user states.
"""

import logging
from bot_core.storage import acquire

logger = logging.getLogger(__name__)

class BaseRepository:
    def __init__(self, table_name: str, primary_key: str = "id"):
        self.table_name = table_name
        self.primary_key = primary_key

    async def create(self, data: dict, replace: bool = False) -> int:
        operator = "INSERT OR REPLACE" if replace else "INSERT"
        columns = ", ".join(data.keys())
        placeholders = ", ".join(["?"] * len(data))
        query = f"{operator} INTO {self.table_name} ({columns}) VALUES ({placeholders})"
        params = tuple(data.values())
        async with acquire() as conn:
            cursor = await conn.execute(query, params)
            await conn.commit()
            last_id = cursor.lastrowid
            return last_id

    async def get_by_id(self, id_value):
        query = f"SELECT * FROM {self.table_name} WHERE {self.primary_key} = ?"
        async with acquire(True) as conn:
            cursor = await conn.execute(query, (id_value,))
            row = await cursor.fetchone()
            return row

    async def update(self, id_value, data: dict) -> None:
        fields = ", ".join([f"{key} = ?" for key in data.keys()])
        query = f"UPDATE {self.table_name} SET {fields} WHERE {self.primary_key} = ?"
        params = tuple(data.values()) + (id_value,)
        async with acquire() as conn:
            await conn.execute(query, params)
            await conn.commit()

    async def delete(self, id_value) -> None:
        query = f"DELETE FROM {self.table_name} WHERE {self.primary_key} = ?"
        async with acquire() as conn:
            await conn.execute(query, (id_value,))
            await conn.commit()

    async def list_all(self, filters: dict = None, order_by: str = None) -> list:
        query = f"SELECT * FROM {self.table_name}"
        params = ()
        if filters:
            conditions = " AND ".join([f"{k} = ?" for k in filters.keys()])
            query += f" WHERE {conditions}"
            params = tuple(filters.values())
        if order_by:
            query += f" ORDER BY {order_by}"
        async with acquire(True) as conn:
            cursor = await conn.execute(query, params)
            rows = await cursor.fetchall()
            return rows or []

    async def delete_by_conditions(self, conditions: dict) -> None:
        cond_str = " AND ".join([f"{key} = ?" for key in conditions.keys()])
        query = f"DELETE FROM {self.table_name} WHERE {cond_str}"
        params = tuple(conditions.values())
        async with acquire() as conn:
            await conn.execute(query, params)
            await conn.commit()

# End of db/repository.py