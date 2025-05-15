"""
db.alembic_helpers
------------------
Shared helpers for running Alembic migrations programmatically.
Moving them here removes duplication between production code
(migrations/env.py) and the test-suite.
"""
from __future__ import annotations
import asyncio
import os
from typing import Callable

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import pool

# --------------------------------------------------------------------- #
# Public helpers                                                        #
# --------------------------------------------------------------------- #
def get_url() -> str:
    """Return the DB URL, respecting the same env-var logic everywhere."""
    return (
        os.environ.get("DB_URL")
        or f"sqlite+aiosqlite:///{os.environ.get('DB_NAME', 'bot_data.db')}"
    )


async def run_async_migrations(do_run_migrations: Callable) -> None:
    """
    Execute *do_run_migrations* using an async SQLAlchemy engine.
    """
    engine = create_async_engine(get_url(), poolclass=pool.NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(do_run_migrations)
    await engine.dispose()


def do_run_migrations(sync_connection) -> None:   # noqa: D401
    """
    Configure Alembic’s context and run migrations with a sync connection.
    """
    from alembic import context as alembic_context   # local import on purpose
    alembic_context.configure(
        connection=sync_connection,
        target_metadata=None,
        compare_type=True,
    )
    with alembic_context.begin_transaction():
        alembic_context.run_migrations()
