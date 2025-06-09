from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from bot.core.api.browser.runner import WebRunner

# Mark all tests in this module as asyncio
pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_settings_fixture(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Mocks settings for browser runner tests."""
    mock_browser_settings = MagicMock(
        headless=True,
        visible=False,
        proxy_enabled=False,
        read_only=False,
        launch_timeout_ms=30000,
    )
    mock_global_settings = MagicMock(
        browser=mock_browser_settings,
        proxy_port=8080,  # Example port
    )

    monkeypatch.setattr("bot.core.api.browser.runner.settings", mock_global_settings)
    return mock_global_settings


@patch("bot.core.api.browser.runner.BrowserEngine")
async def test_web_runner_enqueue_goto_starts_engine_and_processes_command(
    MockBrowserEngine: MagicMock,
    mock_settings_fixture: MagicMock,  # Ensure settings are mocked, now receives the mock
) -> None:
    """Test that enqueueing a 'goto' command starts the BrowserEngine and calls its methods."""
    # Arrange
    mock_engine_instance = AsyncMock()
    MockBrowserEngine.return_value = mock_engine_instance

    runner = WebRunner()
    channel_id = 12345
    test_url = "http://example.com"

    # Act
    task_future = await runner.enqueue(channel_id, "goto", test_url)

    # Allow the worker task to process the command
    # The worker runs _worker, which processes one command then checks queue
    # If queue is empty, it starts a 120s timeout to wait for new command or exit
    # We need to ensure the first command is processed.
    try:
        await asyncio.wait_for(
            task_future, timeout=5.0
        )  # Wait for the specific command future to complete
    except asyncio.TimeoutError:
        pytest.fail("The enqueued command did not complete in time.")

    # Assert
    # Check that BrowserEngine was instantiated correctly
    MockBrowserEngine.assert_called_once_with(
        headless=mock_settings_fixture.browser.headless,  # Using real setting for recreations
        proxy=None,  # Based on mock_settings_fixture proxy_enabled = False
        timeout_ms=mock_settings_fixture.browser.launch_timeout_ms,
    )

    # We no longer call start() to avoid creating an extra about:blank tab
    # Instead, we set browser objects directly in BrowserEngine
    # mock_engine_instance.start.assert_awaited_once()

    # Check that the 'goto' method was called on the engine instance with the correct URL
    mock_engine_instance.goto.assert_awaited_once_with(test_url)

    # Check that the future associated with the command was resolved
    assert task_future.done(), "Command future should be resolved"
    assert task_future.exception() is None, (
        "Command future should not have an exception"
    )

    # Cleanup: Allow the worker to finish its idle timeout and close
    # To ensure the worker exits cleanly, we can try to wait for the queue to be deleted.
    # This part is tricky to test without direct access to the worker task or making it more complex.
    # For now, we assume the primary action (goto) is tested. A more robust test might involve
    # a way to signal the worker to shut down or check self._queues after a delay.

    # A simple way to help worker exit: ensure queue is empty and wait a bit beyond its internal poll
    if channel_id in runner._queues:
        queue = runner._queues[channel_id]
        assert queue.empty(), (
            "Queue should be empty after command processing for worker to consider exiting"
        )

        # The worker waits for 120s on an empty queue. We can't wait that long in a test.
        # For a more robust test of worker shutdown, we'll use a more thorough cleanup approach

        # First, explicitly call close on the engine instance
        await mock_engine_instance.close()
        mock_engine_instance.close.assert_awaited_once()

        # Then find and cancel any WebRunner worker tasks
        tasks = [t for t in asyncio.all_tasks() if "WebRunner._worker" in repr(t)]
        for t in tasks:
            if not t.done():
                t.cancel()
                try:
                    await asyncio.wait_for(
                        t, timeout=1.0
                    )  # Give it a reasonable timeout to clean up
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass  # Expected when cancelling

        # Clean up any remaining Playwright-related tasks to prevent warnings
        tasks = [
            t
            for t in asyncio.all_tasks()
            if "playwright" in repr(t).lower() and not t.done()
        ]
        for t in tasks:
            t.cancel()
            try:
                await asyncio.wait_for(t, timeout=0.5)  # Brief timeout for cleanup
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

        # Verify queue cleanup
        assert channel_id not in runner._queues, (
            "Queue should be removed after worker exits"
        )
