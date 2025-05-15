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

# Import do_run_migrations from env.py for test use
from migrations.env import do_run_migrations

__all__ = ["get_url", "run_async_migrations", "do_run_migrations"]
