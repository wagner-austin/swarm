from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from bot.core.api.browser.runner import WebRunner
from bot.core.api.browser.registry import browser_worker_registry

# Mark all tests in this module as asyncio
pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_settings_fixture(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Mocks settings for browser runner tests."""
    mock_browser_settings = MagicMock(
        headless=True,
        visible=False,
        proxy_enabled=False,  # Ensure this is False for settings.browser.proxy_enabled
        read_only=False,
        launch_timeout_ms=30000,
        worker_idle_timeout_sec=0.1,  # Keep tests fast
        slow_mo=0,  # No slowdown for tests
    )
    mock_global_settings = MagicMock(
        browser=mock_browser_settings,
        proxy_port=8080,  # Example port
        proxy_enabled=False,  # Explicitly set for the test's expectation
    )

    monkeypatch.setattr("bot.core.api.browser.runner.settings", mock_global_settings)
    monkeypatch.setattr(
        "bot.core.api.browser.worker.settings", mock_global_settings
    )  # Patch for worker scope
    return mock_global_settings


@patch("bot.core.api.browser.runner.async_playwright")
@patch("bot.core.api.browser.worker.BrowserEngine")
async def test_web_runner_enqueue_goto_starts_engine_and_processes_command(
    MockBrowserEngine: MagicMock,
    mock_async_playwright: MagicMock,
    mock_settings_fixture: MagicMock,  # Ensure settings are mocked, now receives the mock
) -> None:
    """Test that enqueueing a 'goto' command starts the BrowserEngine and calls its methods."""
    # Arrange
    # Configure mock_settings_fixture for serializable values
    mock_settings_fixture.browser.headless = False
    mock_settings_fixture.browser.slow_mo = 0
    mock_settings_fixture.browser.worker_idle_timeout_sec = (
        0.1  # Fast timeout for tests
    )
    mock_settings_fixture.browser.launch_timeout_ms = 30000

    # Mock the async_playwright integration
    mock_browser = AsyncMock()
    mock_context = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_chromium = AsyncMock()
    mock_chromium.launch = AsyncMock(return_value=mock_browser)
    mock_playwright_instance = AsyncMock(chromium=mock_chromium)
    mock_async_playwright.return_value = AsyncMock(
        __aenter__=AsyncMock(return_value=mock_playwright_instance),
        __aexit__=AsyncMock(),
        start=AsyncMock(return_value=mock_playwright_instance),
    )

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
    # Accessing registry's internal _command_queues directly for test verification purposes
    if channel_id in browser_worker_registry._command_queues:
        queue = browser_worker_registry._command_queues[channel_id]
        assert queue.empty(), (
            "Queue should be empty after command processing for worker to consider exiting"
        )

        # The worker waits for 120s on an empty queue. We can't wait that long in a test.
        # For a more robust test of worker shutdown, we'll use a more thorough cleanup approach

        # Get the worker task from the registry and cancel it
        worker_task = await browser_worker_registry.get_worker_task(channel_id)
        if worker_task:
            if not worker_task.done():
                worker_task.cancel()
                try:
                    # Wait for the task to acknowledge cancellation and run its finally block
                    await asyncio.wait_for(worker_task, timeout=2.0)
                except asyncio.CancelledError:
                    pass
                except asyncio.TimeoutError:
                    pytest.fail(
                        f"Worker task for channel {channel_id} did not finish cleanup in time after cancellation."
                    )
                except Exception as e_await_task:
                    pytest.fail(f"Error awaiting cancelled worker task: {e_await_task}")

            # After attempting cancellation and waiting, check if it's truly done.
            if not worker_task.done():
                pytest.fail(
                    f"Worker task for channel {channel_id} is not done after cancellation and await."
                )
        else:
            # This case might indicate the worker finished and self-removed before explicit cancellation,
            # or was never properly registered. For this test, we expect it to be active before this step.
            # If it already self-removed and cleaned up the queue, the final assertion will pass.
            # However, if it was never registered, other parts of the test should have failed.
            pass  # Allow to proceed to final queue check

        # Assert that the worker called close on the engine instance
        assert mock_engine_instance.close.await_count >= 1, (
            "BrowserEngine.close() should have been called by the worker during cleanup."
        )

        # Give a brief moment for the event loop to process the task removal from the registry
        await asyncio.sleep(0.01)
        await asyncio.sleep(0.1)

        # Clean up any remaining Playwright-related tasks to prevent warnings
        # These are tasks that Playwright itself might have spawned.
        playwright_tasks = [
            t
            for t in asyncio.all_tasks()
            if "playwright" in repr(t).lower() and not t.done()
        ]
        for t_pw in playwright_tasks:
            t_pw.cancel()
            try:
                await asyncio.wait_for(t_pw, timeout=0.5)  # Brief timeout for cleanup
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

        # Verify queue cleanup
        # Verify queue cleanup
        # After worker shutdown and cleanup, the queue should be removed from the registry
        assert channel_id not in browser_worker_registry._command_queues, (
            "Queue should be removed from the registry after worker exits"
        )
