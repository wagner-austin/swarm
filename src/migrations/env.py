import asyncio
from logging.config import fileConfig

from db.alembic_helpers import (
    get_url,
    run_async_migrations,
    do_run_migrations,
)

"""
Alembic context must be imported inside each entry-point function, not at module level.
If imported at the top, repeated programmatic entry (as in test runners or subprocesses)
can overwrite it with None, causing migration failures. Always use a fresh import.
"""

# Alembic config setup moved inside run_migrations_online to avoid import-time errors in test code.


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
            raise RuntimeError(
                "Alembic migration runner called inside a running event loop. Please run run_async_migrations() from your async test fixture."
            )
        else:
            loop.run_until_complete(run_async_migrations(do_run_migrations))
    except RuntimeError:
        # No running loop, safe to use asyncio.run
        asyncio.run(run_async_migrations(do_run_migrations))


if __name__ == "__main__":
    run_migrations_online()

__all__ = ["get_url", "run_async_migrations", "do_run_migrations"]
