import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swarm.core.lifecycle import LifecycleState, SwarmLifecycle
from swarm.core.settings import Settings


@pytest.fixture
def test_settings() -> Settings:
    """Provides a real Settings object for integration tests."""
    return Settings(
        discord_token="fake-token-for-test",
        owner_id=12345,
        # Disable external services for this test
        redis_enabled=False,
        proxy_enabled=False,
    )


REQUIRED_COGS = {
    "MetricsTracker",
    "LoggingAdmin",
    "PersonaAdmin",
    "About",
    "AlertPump",
    "Status",
    "Chat",
    "Web",
    "Shutdown",
    "BrowserHealthMonitor",
}


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
        lifecycle = SwarmLifecycle(settings=test_settings)
        run_task = asyncio.create_task(lifecycle.run())
        # Wait until the bot is initialized and cogs are loaded
        for _ in range(50):
            if hasattr(lifecycle, "_bot") and getattr(lifecycle, "_bot", None):
                break
            await asyncio.sleep(0.05)
        discord_bot = getattr(lifecycle, "_bot", None)
        assert discord_bot is not None, (
            "Discord frontend (discord.py Bot instance) was not created."
        )
        loaded_cogs = {cog.__class__.__name__ for cog in discord_bot.cogs.values()}
        missing = REQUIRED_COGS - loaded_cogs
        assert not missing, f"Missing required cogs: {missing}"
        await lifecycle.shutdown("test_finished")
        run_task.cancel()
        try:
            await run_task
        except Exception:
            pass
