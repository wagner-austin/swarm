"""
tests.helpers
-------------
Centralised utility functions and fixtures for the test-suite.
Add new helpers here instead of sprinkling them across ad-hoc files.
"""

__all__: list[str] = []


import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator


# ------------------------------------------------------------------ #
# Async sleep scaler ------------------------------------------------ #
# ------------------------------------------------------------------ #


@asynccontextmanager
async def override_async_sleep(
    monkeypatch: Any, *, scale: float = 0.01
) -> AsyncGenerator[None, None]:
    """
    Temporarily monkey-patch ``asyncio.sleep`` so that real sleeps
    are divided by *scale*.  Handy for speeding up slow background
    tasks in tests.
    """
    original_sleep = asyncio.sleep

    async def fast_sleep(seconds: float) -> None:
        return await original_sleep(seconds * scale)

    monkeypatch.setattr(asyncio, "sleep", fast_sleep)
    try:
        yield
    finally:
        monkeypatch.setattr(asyncio, "sleep", original_sleep)


# Removed DB helpers – no persistent storage layer remains
