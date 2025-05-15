import asyncio
from logging.config import fileConfig
import os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import pool

# Helper to get DB URL
def get_url() -> str:
    return os.environ.get("DB_URL") or f"sqlite+aiosqlite:///{os.environ.get('DB_NAME', 'bot_data.db')}"

# Async migration runner (to be imported by tests and env.py)
async def run_async_migrations(do_run_migrations):
    engine = create_async_engine(get_url(), poolclass=pool.NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(do_run_migrations)
    await engine.dispose()

"""
Alembic context must be imported inside each entry-point function, not at module level.
If imported at the top, repeated programmatic entry (as in test runners or subprocesses)
can overwrite it with None, causing migration failures. Always use a fresh import.
"""

# Alembic config setup moved inside run_migrations_online to avoid import-time errors in test code.

# ---------- NEW helpers ----------
def do_run_migrations(sync_connection):
    """
    Run migrations with a plain sync connection that Alembic gives us.
    Uses a lazy import for alembic.context for idempotence and test safety.
    """
    from alembic import context as alembic_context  # lazy, scoped import
    alembic_context.configure(
        connection=sync_connection,
        target_metadata=None,        # <-- add if you have metadata later
        compare_type=True,           # keep autogenerate sane
    )
    with alembic_context.begin_transaction():
        alembic_context.run_migrations()     # no extra args!

# ---------- entry-point ----------
def run_migrations_online() -> None:
    """
    Alembic entry point. Uses a lazy import for alembic.context for idempotence and test safety.
    """
    from alembic import context as alembic_context  # lazy, scoped import
    config = alembic_context.config
    if config.config_file_name:
        fileConfig(config.config_file_name)
    try:
        loop = asyncio.get_running_loop()
        if loop.is_running():
            # Running inside pytest-asyncio or similar; do NOT run migrations here.
            # Instead, run run_async_migrations() from your test fixture using 'await'.
            raise RuntimeError("Alembic migration runner called inside a running event loop. Please run run_async_migrations() from your async test fixture.")
        else:
            loop.run_until_complete(run_async_migrations(do_run_migrations))
    except RuntimeError:
        # No running loop, safe to use asyncio.run
        asyncio.run(run_async_migrations(do_run_migrations))

if __name__ == "__main__":
    run_migrations_online()

__all__ = ["get_url", "run_async_migrations", "do_run_migrations"]
