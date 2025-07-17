from __future__ import annotations

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


@pytest.mark.asyncio
async def test_full_bot_startup_wiring(
    test_settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    """Verify that the bot's DI container and lifecycle can be fully wired without errors."""
    # Create an event to control when the mocked swarm.start() should finish
    start_event = asyncio.Event()

    async def mock_start_blocking(token: str) -> None:
        """Mock swarm.start() that blocks until we signal it to finish."""
        await start_event.wait()

    # Patch the actual Discord connection methods to avoid real network calls
    with (
        patch("swarm.core.discord.boot.MyBot.start", side_effect=mock_start_blocking),
        patch("swarm.core.discord.boot.MyBot.close", new_callable=AsyncMock),
        patch("swarm.core.discord.boot.MyBot.login", new_callable=AsyncMock),
    ):
        lifecycle = SwarmLifecycle(settings=test_settings)

        # The `run` method normally blocks forever. We'll run it as a task and
        # cancel it once we've verified it has reached the connecting state.
        run_task = asyncio.create_task(lifecycle.run())

        # Allow the lifecycle to progress. We expect it to stop at the `start()` call.
        # We use a helper function to wait until the desired state is reached or timeout.
        async def wait_for_state(target_state: LifecycleState, timeout: float = 5.0) -> None:
            waited = 0.0
            while lifecycle.state != target_state and waited < timeout:
                await asyncio.sleep(0.1)
                waited += 0.1
                # Check if the run_task has completed (which would indicate an error)
                if run_task.done():
                    try:
                        await run_task  # This will raise any exception that occurred
                    except Exception as e:
                        pytest.fail(
                            f"Lifecycle task failed with exception: {e}\n"
                            f"Current state: {lifecycle.state.name}\n"
                            f"Captured logs: {caplog.text}"
                        )
            if lifecycle.state != target_state:
                # Provide more debugging information
                task_status = "completed" if run_task.done() else "still running"
                pytest.fail(
                    f"Lifecycle did not reach {target_state.name} within {timeout}s.\n"
                    f"Current state: {lifecycle.state.name}\n"
                    f"Run task status: {task_status}\n"
                    f"Captured logs: {caplog.text}"
                )

        # The lifecycle should proceed through states and stop at CONNECTING_TO_DISCORD
        # right before it calls the patched `swarm.start()`.
        await wait_for_state(LifecycleState.CONNECTING_TO_DISCORD)

        # Success! The lifecycle reached CONNECTING_TO_DISCORD, meaning all DI container
        # wiring and initialization completed without errors

        # Signal the mock swarm.start() to complete so lifecycle can proceed to shutdown
        start_event.set()

        # Wait a moment for the lifecycle to process the mock swarm.start() completion
        await asyncio.sleep(0.1)

        # Cleanly shut down the lifecycle
        await lifecycle.shutdown("test_finished")
        run_task.cancel()
        try:
            await run_task
        except asyncio.CancelledError:
            pass

        assert lifecycle.state == LifecycleState.STOPPED
