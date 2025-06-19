"""
tests/core/test_metrics.py - Tests for the metrics module.
Ensures uptime and message counting functionality work as expected.
"""

import pytest

import bot.core.metrics as metrics


@pytest.mark.asyncio
async def test_get_uptime() -> None:
    uptime = metrics.get_uptime()
    assert isinstance(uptime, float)
    assert uptime >= 0


@pytest.mark.asyncio
async def test_increment_message_count() -> None:
    initial_count = metrics.messages_sent
    metrics.increment_message_count()
    assert metrics.messages_sent == initial_count + 1
