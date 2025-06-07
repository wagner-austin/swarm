#!/usr/bin/env python
"""
tests/core/test_database_schema.py - Tests for the database schema module.
Verifies that init_db creates the necessary table: SchemaVersion.
"""

import pytest
from src.bot_core.api import db_api
import pytest_asyncio
from typing import Any, AsyncGenerator


@pytest_asyncio.fixture(scope="function", autouse=True)
async def reset_user_state() -> AsyncGenerator[None, None]:
    """
    Fixture to initialize the DB schema once per test session and reset UserStates between tests.
    Runs Alembic migrations and clears UserStates table between tests.
    """
    # Alembic migrations are already applied session-wide in conftest.py.
    # Only clear UserStates table here.

    async def clear_user_states() -> None:
        row = await db_api.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='UserStates'"
        )
        if row is not None:
            await db_api.execute_query("DELETE FROM UserStates", commit=True)

    await clear_user_states()
    yield
    await clear_user_states()


@pytest.mark.asyncio
async def test_init_db_creates_tables(async_db: Any) -> None:
    # Check for the SchemaVersion table using async DB API
    row = await db_api.fetch_one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='SchemaVersion'"
    )
    assert row == {"name": "SchemaVersion"}, (
        f"SchemaVersion table not created or row incorrect: {row}"
    )
