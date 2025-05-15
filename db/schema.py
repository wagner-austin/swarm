#!/usr/bin/env python
"""
db/schema.py --- Database schema initialization for the bot.
Ensures the SQLite database file exists.
"""

from .connection import db_connection

def init_db() -> None:
    """
    init_db - Ensure the SQLite database file exists and has SchemaVersion table.
    """
    with db_connection() as conn:
        cursor = conn.cursor()

        # SchemaVersion table (bumped to version 2: Flow system removed)
        cursor.execute("DROP TABLE IF EXISTS SchemaVersion")
        cursor.execute("""
        CREATE TABLE SchemaVersion (
            version INTEGER PRIMARY KEY
        )
        """)
        cursor.execute("INSERT INTO SchemaVersion (version) VALUES (2)")
        conn.commit()

# End of db/schema.py