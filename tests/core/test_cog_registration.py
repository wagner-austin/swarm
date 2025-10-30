import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis as fakeredis_aioredis
import pytest

from swarm.core.cogs_registry import required_cog_names
from swarm.core.lifecycle import LifecycleState, SwarmLifecycle
from swarm.core.settings import Settings
from swarm.infra.redis_protocols import wrap_redis_async


@pytest.fixture
def test_settings() -> Settings:
    """Provides a real Settings object for integration tests."""
    return Settings(
        discord_token="fake-token-for-test",
        owner_id=12345,
        # Enable Redis via nested config so BrowserHealthMonitor is registered
        redis={"enabled": True, "url": "redis://localhost:6379/0"},
        proxy_enabled=False,
    )


@pytest.mark.asyncio
async def test_all_required_cogs_registered(test_settings: Settings) -> None:
    """Test that all critical cogs are registered with the bot after startup."""

    async def mock_start_blocking(token: str) -> None:
        pass  # Immediately return for test

    with (
        patch("swarm.core.discord.boot.MyBot.start", side_effect=mock_start_blocking),
        patch("swarm.core.discord.boot.MyBot.close", new_callable=AsyncMock),
        patch("swarm.core.discord.boot.MyBot.login", new_callable=AsyncMock),
    ):
        # Build a real container and override Redis provider with fakeredis
        from swarm.core.containers import Container

        container = Container()
        container.config.override(test_settings)
        fake = wrap_redis_async(fakeredis_aioredis.FakeRedis(decode_responses=True))
        container.redis_client.override(fake)

        lifecycle = SwarmLifecycle(settings=test_settings, container=container)
        run_task = asyncio.create_task(lifecycle.run())
        # Wait until all extensions are loaded deterministically
        await asyncio.wait_for(lifecycle.extensions_loaded_event.wait(), timeout=5.0)
        discord_bot = getattr(lifecycle, "_bot", None)
        assert discord_bot is not None, (
            "Discord frontend (discord.py Bot instance) was not created."
        )
        loaded_cogs = {cog.__class__.__name__ for cog in discord_bot.cogs.values()}
        expected_cogs = required_cog_names(test_settings)
        missing = expected_cogs - loaded_cogs
        assert not missing, f"Missing required cogs: {missing}"
        await lifecycle.shutdown("test_finished")
        run_task.cancel()
        try:
            await run_task
        except Exception:
            pass
