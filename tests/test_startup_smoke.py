# File: tests/test_startup_smoke.py


from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# ── internal entry-points we want to exercise ─────────────────────────
# ── internal entry-points we want to exercise ─────────────────────────
from swarm.core.lifecycle import SwarmLifecycle
from swarm.core.settings import Settings


@pytest.mark.asyncio
async def test_swarm_startup_smoke() -> None:
    """
    Boots the full discord-runner stack, but with the primary external side-effect
    (the Discord API) stubbed out so the coroutine returns immediately.

    The goal is to detect regressions in the startup path (import cycles, bad
    awaits, missing attrs) without hitting the network.
    """

    # ------------------------------------------------------------------
    # 1.  Create a fake bot factory that produces a mock bot instance.
    #     This mock simulates the behavior needed for the smoke test.
    # ------------------------------------------------------------------
    def fake_swarm_factory(*args: Any, **kwargs: Any) -> MagicMock:
        mock_discord_bot = MagicMock()

        # The bot factory receives intents and container, we need to store the container
        # so that cogs can access it via discord_bot.container during initialization
        mock_discord_bot.container = kwargs.get("container")

        async def fake_start(*args: Any, **kwargs: Any) -> None:
            # Immediately raise KeyboardInterrupt to simulate a graceful shutdown signal,
            # allowing us to test the full startup and shutdown sequence.
            raise KeyboardInterrupt

        mock_discord_bot.start = fake_start
        mock_discord_bot.close = AsyncMock()
        mock_discord_bot.is_closed.return_value = True
        return mock_discord_bot

    # ------------------------------------------------------------------
    # 2.  Create a settings object for the test.
    # ------------------------------------------------------------------
    settings = Settings(discord_token="fake-token-for-test")

    # ------------------------------------------------------------------
    # 3.  Instantiate the lifecycle manager, injecting our fake bot factory.
    # ------------------------------------------------------------------
    lifecycle = SwarmLifecycle(settings=settings, swarm_factory=fake_swarm_factory)

    # ------------------------------------------------------------------
    # 4.  Run the lifecycle. If any step raises an unexpected error,
    #     pytest will fail the test.
    # ------------------------------------------------------------------
    await lifecycle.run()
