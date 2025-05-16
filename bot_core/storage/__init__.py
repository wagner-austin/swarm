from contextlib import asynccontextmanager
import aiosqlite
from bot_core.settings import settings
from typing import AsyncGenerator


@asynccontextmanager
async def acquire(readonly: bool = False) -> AsyncGenerator[aiosqlite.Connection, None]:
    mode = "ro" if readonly else "rwc"
    async with aiosqlite.connect(
        f"file:{settings.db_name}?mode={mode}", uri=True
    ) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        yield conn


@asynccontextmanager
async def transaction(
    exclusive: bool = False,
) -> AsyncGenerator[aiosqlite.Connection, None]:
    async with acquire() as conn:
        await conn.execute("BEGIN EXCLUSIVE" if exclusive else "BEGIN IMMEDIATE")
        try:
            yield conn
        finally:
            await conn.commit()


@asynccontextmanager
async def noop_tx() -> AsyncGenerator[aiosqlite.Connection, None]:
    async with acquire() as conn:
        yield conn
