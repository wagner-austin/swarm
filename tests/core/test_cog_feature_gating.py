from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import fakeredis.aioredis as fakeredis_aioredis
import pytest

from swarm.core.cogs_registry import required_cog_names
from swarm.core.containers import Container
from swarm.core.lifecycle import SwarmLifecycle
from swarm.core.settings import Settings
from swarm.history.in_memory import MemoryBackend
from swarm.infra.redis_protocols import wrap_redis_async


@pytest.mark.asyncio
async def test_feature_gated_cogs_loaded_when_enabled() -> None:
    settings = Settings(
        discord_token="fake-token-for-test",
        owner_id=12345,
        redis={"enabled": True, "url": "redis://localhost:6379/0"},
        proxy_enabled=False,
    )

    with (
        patch("swarm.core.discord.boot.MyBot.start", new=AsyncMock()),
        patch("swarm.core.discord.boot.MyBot.close", new=AsyncMock()),
        patch("swarm.core.discord.boot.MyBot.login", new=AsyncMock()),
    ):
        container = Container()
        container.config.override(settings)
        fake = wrap_redis_async(fakeredis_aioredis.FakeRedis(decode_responses=True))
        container.redis_client.override(fake)

        lifecycle = SwarmLifecycle(settings=settings, container=container)
        run_task = asyncio.create_task(lifecycle.run())
        await asyncio.wait_for(lifecycle.extensions_loaded_event.wait(), timeout=5.0)

        bot = getattr(lifecycle, "_bot", None)
        assert bot is not None
        # BrowserHealthMonitor should be present when Redis is enabled
        assert bot.get_cog("BrowserHealthMonitor") is not None

        expected = required_cog_names(settings)
        loaded = {c.__class__.__name__ for c in bot.cogs.values()}
        assert expected == loaded

        await lifecycle.shutdown("test_finished")
        run_task.cancel()
        try:
            await run_task
        except Exception:
            pass


@pytest.mark.asyncio
async def test_feature_gated_cogs_skipped_when_disabled() -> None:
    settings = Settings(
        discord_token="fake-token-for-test",
        owner_id=12345,
        redis={"enabled": False},
        proxy_enabled=False,
    )

    with (
        patch("swarm.core.discord.boot.MyBot.start", new=AsyncMock()),
        patch("swarm.core.discord.boot.MyBot.close", new=AsyncMock()),
        patch("swarm.core.discord.boot.MyBot.login", new=AsyncMock()),
    ):
        container = Container()
        container.config.override(settings)
        # Provide an explicit in-memory history backend when Redis is disabled
        container.history_backend.override(MemoryBackend())

        lifecycle = SwarmLifecycle(settings=settings, container=container)
        run_task = asyncio.create_task(lifecycle.run())
        await asyncio.wait_for(lifecycle.extensions_loaded_event.wait(), timeout=5.0)

        bot = getattr(lifecycle, "_bot", None)
        assert bot is not None
        # BrowserHealthMonitor should be absent when Redis is disabled
        assert bot.get_cog("BrowserHealthMonitor") is None

        expected = required_cog_names(settings)
        loaded = {c.__class__.__name__ for c in bot.cogs.values()}
        assert expected == loaded

        await lifecycle.shutdown("test_finished")
        run_task.cancel()
        try:
            await run_task
        except Exception:
            pass
