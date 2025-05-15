#!/usr/bin/env python
"""
tests/async_helpers.py - Common asynchronous test helper functions.
Provides an async context manager to override asyncio.sleep for speeding up asynchronous tests.
"""

import asyncio
from contextlib import asynccontextmanager

@asynccontextmanager
async def override_async_sleep(monkeypatch, scale=0.01):
    """
    override_async_sleep - Temporarily overrides asyncio.sleep to scale down sleep duration.
    
    Args:
        monkeypatch: Pytest monkeypatch fixture.
        scale (float): Factor to scale down the sleep duration.
        
    Yields:
        None. Ensures that asyncio.sleep is restored after usage.
    """
    original_sleep = asyncio.sleep

    async def fast_sleep(seconds):
        return await original_sleep(seconds * scale)

    monkeypatch.setattr(asyncio, "sleep", fast_sleep)
    try:
        yield
    finally:
        monkeypatch.setattr(asyncio, "sleep", original_sleep)

# End of tests/async_helpers.py