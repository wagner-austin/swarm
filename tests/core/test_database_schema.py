#!/usr/bin/env python
"""
tests/core/test_database_schema.py - Tests for the database schema module.
Verifies that init_db creates the necessary table: SchemaVersion.
"""

import pytest
import subprocess
import pathlib
from bot_core.api import db_api
from alembic.config import Config
import pytest_asyncio
from migrations.runner import run_async_migrations  # Import the async migration runner
from migrations.env import do_run_migrations  # Import the migration logic

@pytest_asyncio.fixture(scope="function", autouse=True)
async def reset_user_state():
    """
    Fixture to initialize the DB schema once per test session and reset UserStates between tests.
    Runs Alembic migrations and clears UserStates table between tests.
    """
    # Alembic migrations are already applied session-wide in conftest.py.
    # Only clear UserStates table here.

    async def clear_user_states():
        row = await db_api.fetch_one("SELECT name FROM sqlite_master WHERE type='table' AND name='UserStates'")
        if row is not None:
            await db_api.execute_query("DELETE FROM UserStates", commit=True)
    await clear_user_states()
    yield
    await clear_user_states()


@pytest.mark.asyncio
async def test_init_db_creates_tables(async_db):
    # Check for the SchemaVersion table using async DB API
    row = await db_api.fetch_one("SELECT name FROM sqlite_master WHERE type='table' AND name='SchemaVersion'")
    assert row is not None, "SchemaVersion table not created."

# End of tests/core/test_database_schema.py