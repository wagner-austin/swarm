from __future__ import annotations

import asyncio
import logging
from typing import Any

from playwright.async_api import (
    Playwright,
    async_playwright,
    Browser,
    BrowserContext,
    Error as PlaywrightError,
)

from bot.core.api.browser.signals import SHUTDOWN_SENTINEL
from bot.core.browser_manager import browser_manager, Runner
from bot.core.settings import settings

# Refactored imports
from .command import Command
from .registry import browser_worker_registry
from .worker import browser_worker

log = logging.getLogger(__name__)


class WebRunner:
    """
    Public facade for managing browser interactions.
    Enqueues commands and manages the lifecycle of browser workers.
    One worker (and its associated browser context) is created per channel_id.
    """

    async def enqueue(
        self, channel_id: int, action: str, *args: Any, **kwargs: Any
    ) -> asyncio.Future[Any]:
        """Enqueues a command to be run in the browser context for the given channel_id."""
        """
        Enqueues a browser command for a given channel.
        If no worker is active for the channel, it starts one.
        """
        loop = asyncio.get_event_loop()
        command_future: asyncio.Future[Any] = loop.create_future()
        cmd = Command(action=action, args=args, kwargs=kwargs, future=command_future)

        command_queue = await browser_worker_registry.get_or_create_queue(channel_id)
        try:
            command_queue.put_nowait(cmd)
        except asyncio.QueueFull:
            log.error(
                f"Command queue full for channel {channel_id}. Command '{action}' dropped."
            )
            # Immediately fail the future if the queue is full
            command_future.set_exception(
                RuntimeError(f"Browser command queue for channel {channel_id} is full.")
            )
            return command_future

        # Check if a worker is already active or if its task is retrievable and not done.
        # The browser_manager stores the Runner object which includes the worker_task.
        # The registry also stores the worker_task. We can use either, but registry is simpler here.
        if not await browser_worker_registry.is_worker_active(channel_id):
            log.info(
                f"No active worker for channel {channel_id}. Attempting to start a new one."
            )
            # No active worker, or previous worker finished. Start a new one.
            # This block is responsible for creating Playwright resources and the worker task.
            playwright_object: Playwright | None = None
            browser_instance: Browser | None = None
            context_instance: BrowserContext | None = None
            worker_task_instance: asyncio.Task[Any] | None = None

            try:
                playwright_object = await async_playwright().start()
                # slow_mo is now defined in BrowserConfig with a default of 0
                # If slow_mo is 0 (default), use 100ms if not headless, else 0.
                # If slow_mo is explicitly set to non-zero, use that value.
                slow_mo_val = settings.browser.slow_mo
                if slow_mo_val == 0:
                    slow_mo_val = 100 if not settings.browser.headless else 0

                browser_instance = await playwright_object.chromium.launch(
                    headless=settings.browser.headless,
                    slow_mo=slow_mo_val,
                )
                context_instance = await browser_instance.new_context(
                    # Pass any context options from settings if available
                )
                # Removed context_options expansion as per review feedback; BrowserConfig does not define it.

                # Create and start the new worker task
                worker_task_instance = loop.create_task(
                    browser_worker(
                        channel_id,
                        command_queue,  # The queue obtained from the registry
                        playwright_object,
                        browser_instance,
                        context_instance,
                    )
                )
                # Store the worker task in the registry
                await browser_worker_registry.add_worker_task(
                    channel_id, worker_task_instance
                )

                # Register with BrowserManager
                # The Runner object now primarily serves browser_manager for resource tracking.
                # The actual worker logic is in browser_worker.
                runner_data = Runner(
                    channel_id=channel_id,
                    playwright=playwright_object,  # Pass the Playwright instance
                    browser=browser_instance,
                    context=context_instance,
                    queue=command_queue,
                    worker_task=worker_task_instance,
                )
                await browser_manager.register(runner_data)
                log.info(
                    f"New browser worker started and registered for channel {channel_id}."
                )

            except PlaywrightError as e_pw:
                log.error(
                    f"Playwright error during worker startup for channel {channel_id}: {e_pw}",
                    exc_info=True,
                )
                command_future.set_exception(e_pw)
                await self._cleanup_failed_startup(
                    channel_id,
                    playwright_object,
                    browser_instance,
                    worker_task_instance,
                )
                return command_future
            except Exception as e:
                log.error(
                    f"Failed to create and start browser worker for channel {channel_id}: {e}",
                    exc_info=True,
                )
                if not command_future.done():  # Ensure future is only set once
                    command_future.set_exception(e)
                # Cleanup resources on failure
                await self._cleanup_failed_startup(
                    channel_id,
                    playwright_object,
                    browser_instance,
                    worker_task_instance,
                )
                return command_future
        else:
            log.debug(
                f"Worker already active for channel {channel_id}. Command enqueued."
            )

        return command_future

    async def _cleanup_failed_startup(
        self,
        channel_id: int,
        playwright: Playwright | None,
        browser: Browser | None,
        worker_task: asyncio.Task[Any] | None,
    ) -> None:
        """Helper to clean up resources if worker startup fails."""
        log.warning(
            f"Cleaning up resources after failed worker startup for channel {channel_id}."
        )
        if worker_task and not worker_task.done():
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                log.debug(
                    f"Worker task for channel {channel_id} cancelled during cleanup."
                )
            except Exception as e_task_cleanup:
                log.error(
                    f"Error awaiting cancelled worker task for {channel_id}: {e_task_cleanup}"
                )

        # Attempt to close browser and playwright resources if they were created
        if browser:
            try:
                await browser.close()
                log.debug(f"Browser for channel {channel_id} closed during cleanup.")
            except Exception as e_browser:
                log.error(
                    f"Error closing browser for channel {channel_id} during cleanup: {e_browser}"
                )
        if playwright:
            try:
                await playwright.stop()
                log.debug(
                    f"Playwright for channel {channel_id} stopped during cleanup."
                )
            except Exception as e_pw:
                log.error(
                    f"Error stopping playwright for channel {channel_id} during cleanup: {e_pw}"
                )

        # Ensure info is removed from registry and manager
        await browser_worker_registry.remove_worker_info(
            channel_id
        )  # Cleans up queue if empty, and task
        try:
            # Unregister might fail if it was never registered, or if already unregistered by worker.
            # This is a best-effort cleanup.
            await browser_manager.unregister(channel_id)
        except Exception as e_unreg:
            log.debug(
                f"Issue unregistering channel {channel_id} from browser_manager during cleanup: {e_unreg}"
            )

    async def shutdown_channel_worker(self, channel_id: int, wait: bool = True) -> None:
        """
        Attempts to gracefully shut down the worker for a specific channel.
        Sends a sentinel to the queue and optionally waits for the worker task to complete.
        """
        log.info(f"Requesting shutdown for worker of channel {channel_id}.")
        worker_task = await browser_worker_registry.get_worker_task(channel_id)
        command_queue = await browser_worker_registry.get_or_create_queue(
            channel_id
        )  # Get queue even if task is gone

        if worker_task and not worker_task.done():
            log.debug(
                f"Worker task for channel {channel_id} is active. Sending None sentinel to queue."
            )
            try:
                command_queue.put_nowait(
                    SHUTDOWN_SENTINEL
                )  # Sentinel to signal worker to stop
            except asyncio.QueueFull:
                log.warning(
                    f"Queue full for channel {channel_id}, cannot send shutdown sentinel. Forcing cancel."
                )
                worker_task.cancel()  # Force cancel if queue is full

            if wait:
                try:
                    await asyncio.wait_for(
                        worker_task, timeout=30.0
                    )  # Wait for worker to finish
                    log.info(f"Worker for channel {channel_id} shut down gracefully.")
                except asyncio.TimeoutError:
                    log.warning(
                        f"Timeout waiting for worker {channel_id} to shut down. Forcing cancel."
                    )
                    if not worker_task.done():
                        worker_task.cancel()
                except asyncio.CancelledError:
                    log.info(
                        f"Shutdown wait for worker {channel_id} was cancelled."
                    )  # Task itself was cancelled
                except Exception as e:
                    log.error(
                        f"Error during supervised shutdown of worker {channel_id}: {e}",
                        exc_info=True,
                    )
                    if not worker_task.done():
                        worker_task.cancel()  # Ensure it's cancelled on other errors
        elif worker_task and worker_task.done():
            log.info(f"Worker task for channel {channel_id} already done.")
        else:
            log.info(
                f"No active worker task found for channel {channel_id} to shut down."
            )

        # Final cleanup from registry, in case worker didn't (e.g. if it crashed)
        # The worker's finally block should call this, but this is a safeguard.
        await browser_worker_registry.remove_worker_info(channel_id)

    async def close(self) -> None:
        """
        Convenience method for cog_unload() handlers to shut down all browser workers.
        Simply delegates to shutdown_all_workers() with wait=True.
        """
        await self.shutdown_all_workers(wait=True)

    async def shutdown_all_workers(self, wait: bool = True) -> None:
        """
        Attempts to gracefully shut down all active browser workers.
        """
        log.info("Attempting to shut down all active browser workers.")
        # Get a list of channel_ids that have active workers from the registry
        # Iterate over a copy of task keys as shutdown_channel_worker modifies the underlying dict
        active_channel_ids = list(browser_worker_registry._active_worker_tasks.keys())

        shutdown_tasks = [
            self.shutdown_channel_worker(
                channel_id, wait=False
            )  # Don't wait individually here
            for channel_id in active_channel_ids
        ]
        results = await asyncio.gather(*shutdown_tasks, return_exceptions=True)

        for channel_id, result in zip(active_channel_ids, results):
            if isinstance(result, Exception):
                log.error(
                    f"Error shutting down worker for channel {channel_id}: {result}"
                )

        if (
            wait and active_channel_ids
        ):  # Only wait if we actually shut down workers and wait is true
            # After signaling all workers, wait for their tasks to complete.
            # This relies on browser_manager holding the tasks.
            # Alternatively, collect tasks from registry before they are removed.
            all_worker_tasks = await browser_manager.get_all_worker_tasks()

            if all_worker_tasks:
                log.info(
                    f"Waiting for {len(all_worker_tasks)} worker tasks to complete shutdown..."
                )
                try:
                    await asyncio.wait(
                        all_worker_tasks, timeout=60.0
                    )  # Overall timeout
                    log.info("All signaled worker tasks have completed.")
                except asyncio.TimeoutError:
                    log.warning(
                        "Timeout waiting for all worker tasks to complete. Some may still be running/stuck."
                    )
                    # Optionally, iterate and cancel any remaining tasks
                    for task in all_worker_tasks:
                        if not task.done():
                            log.warning(
                                f"Forcing cancel on task {task.get_name()} due to overall shutdown timeout."
                            )
                            task.cancel()
                except Exception as e:
                    log.error(
                        f"Exception while waiting for all worker tasks to complete: {e}",
                        exc_info=True,
                    )
            else:
                log.info(
                    "No active worker tasks found to wait for during shutdown_all_workers."
                )
        log.info("Finished shutdown_all_workers sequence.")
