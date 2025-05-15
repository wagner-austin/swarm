#!/usr/bin/env python
"""
db/schema.py --- Database schema initialization for the bot.
Ensures the SQLite database file exists.
"""

from .connection import db_connection

def init_db() -> None:
    """
    init_db - Ensure the SQLite database file exists and has UserStates and SchemaVersion tables.
    """
    with db_connection() as conn:
        cursor = conn.cursor()
        # UserStates table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS UserStates (
            user_id TEXT PRIMARY KEY,
            flow_state TEXT DEFAULT '{}'
        )
        """)
        # Migration logic to rename 'phone' to 'user_id' if needed
        cursor.execute("""
        PRAGMA table_info(UserStates)
        """)
        rows = cursor.fetchall()
        if any(row[1] == 'phone' for row in rows):
            cursor.execute("""
            ALTER TABLE UserStates RENAME COLUMN phone TO user_id
            """)
        # SchemaVersion table
        cursor.execute("DROP TABLE IF EXISTS SchemaVersion")
        cursor.execute("""
        CREATE TABLE SchemaVersion (
            version INTEGER PRIMARY KEY
        )
        """)
        cursor.execute("INSERT INTO SchemaVersion (version) VALUES (1)")
        conn.commit()

# End of db/schema.py