from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from playwright.async_api import (
    Playwright,
    Browser,
    BrowserContext,
    Error as PlaywrightError,
)

from .command import Command
from .engine import BrowserEngine
from .registry import browser_worker_registry
from .signals import SHUTDOWN_SENTINEL
from bot.core.browser_manager import browser_manager
from bot.core.settings import settings


log = logging.getLogger(__name__)


async def browser_worker(
    channel_id: int,
    queue: asyncio.Queue[Command | object],
    playwright_object: Playwright,
    browser_instance: Browser,
    context_instance: BrowserContext,
) -> None:
    """
    Worker coroutine that processes commands for a single browser context.
    Manages a BrowserEngine instance and handles command execution and idle timeouts.
    """
    eng: BrowserEngine | None = None
    log.info(f"Browser worker starting for channel {channel_id}.")

    try:
        # Initialize the BrowserEngine for this worker
        proxy_server_str: str | None = None
        if settings.browser.proxy_enabled and settings.proxy_port:
            proxy_server_str = f"http://127.0.0.1:{settings.proxy_port}"

        eng = BrowserEngine(
            headless=settings.browser.headless,
            proxy=proxy_server_str,
            timeout_ms=settings.browser.launch_timeout_ms,
        )
        # Assign the pre-created Playwright resources to this BrowserEngine instance
        eng._playwright = playwright_object
        eng._browser = browser_instance
        eng._context = context_instance
        # eng.start() should not be called here, as resources are managed externally by WebRunner
        # and passed into this worker. BrowserEngine will use these assigned resources.
        log.info(f"BrowserEngine created for channel {channel_id}.")
        # Create a page directly from the provided context, don't use _ensure_page() which would create a new context
        eng._page = await context_instance.new_page()

        while True:
            cmd: Command | object = None
            try:
                # Wait for a command from the queue
                log.debug(f"Worker for channel {channel_id} waiting for command.")
                cmd = await queue.get()
            except asyncio.CancelledError:
                log.info(
                    f"Worker for channel {channel_id} queue.get() cancelled. Exiting loop."
                )
                raise  # Re-raise to be caught by the outer try/except asyncio.CancelledError

            if cmd is SHUTDOWN_SENTINEL:  # Sentinel value to indicate shutdown
                log.info(
                    f"Worker for channel {channel_id} received shutdown sentinel. Shutting down."
                )
                # Call queue.task_done() even for sentinel for proper queue.join() semantics
                queue.task_done()
                break  # Exit the main processing loop

            # Assert that cmd is a dictionary (Command) before proceeding to index it.
            if not isinstance(cmd, dict):
                log.error(
                    f"Worker for channel {channel_id} received unexpected non-dict/non-sentinel item from queue: {type(cmd)} - {cmd!r}. Skipping."
                )
                queue.task_done()  # Mark this unexpected, skipped item as done.
                continue

            # If we reach here, cmd is confirmed to be a dict (Command).
            log.debug(
                f"Channel {channel_id}: Processing command '{cmd['action']}' with args {cmd.get('args', [])}, kwargs {cmd.get('kwargs', {})}"
            )
            try:
                action_method_name = cmd["action"]
                if not hasattr(eng, action_method_name):
                    raise AttributeError(
                        f"BrowserEngine has no action '{action_method_name}'"
                    )

                action_method: Callable[..., Awaitable[Any]] = getattr(
                    eng, action_method_name
                )
                if not callable(action_method):
                    raise TypeError(
                        f"BrowserEngine action '{action_method_name}' is not callable"
                    )

                result = await action_method(*cmd["args"], **cmd["kwargs"])

                if not cmd["future"].done():
                    cmd["future"].set_result(result)
                log.debug(
                    f"Channel {channel_id}: Command '{cmd['action']}' executed successfully."
                )

            except PlaywrightError as e_pw:
                # Check if it's a browser-closed error vs transient network error
                error_msg = str(e_pw).lower()
                if (
                    "browser has been closed" in error_msg
                    or "context has been closed" in error_msg
                ):
                    log.warning(
                        f"Browser closed during action '{cmd['action']}' for channel {channel_id}: {e_pw}"
                    )
                    # Resolve the Future with a friendly message instead of an exception
                    if not cmd["future"].done():
                        cmd["future"].set_result(
                            f"❌ Browser closed during '{cmd['action']}'. "
                            "Restart with /web start."
                        )
                    # Break out of loop to shut down worker gracefully
                    break
                else:
                    # Likely a transient network error or other Playwright issue
                    log.error(
                        f"Playwright error executing action '{cmd['action']}' for channel {channel_id}: {e_pw}",
                        exc_info=True,
                    )
                    if not cmd["future"].done():
                        cmd["future"].set_exception(e_pw)
            except Exception as e:  # General errors during command execution
                log.error(
                    f"Error executing action '{cmd['action']}' for channel {channel_id}: {e}",
                    exc_info=True,
                )
                if not cmd["future"].done():
                    cmd["future"].set_exception(e)
            finally:
                # A command (not None) was retrieved from the queue, so task_done must be called.
                queue.task_done()

            # Idle timeout logic: if queue is empty, start an idle timer.
            # The worker will shut down if no new command arrives within the timeout.
            log.debug(f"Channel {channel_id} queue empty, starting idle timer.")
            wait_for_new_command_task = None  # Initialize before try block
            try:
                # Micro-optimization: create_task() inside try, only if no shutdown sentinel
                wait_for_new_command_task = asyncio.create_task(queue.get())
                new_cmd = await asyncio.wait_for(
                    wait_for_new_command_task,
                    timeout=settings.browser.worker_idle_timeout_sec,
                )

                # If a new command arrives before timeout
                log.debug(
                    f"Channel {channel_id} received new command while idle, continuing worker."
                )
                # Re-queue the command to be handled by the main loop
                # Don't call queue.task_done() here - the main loop will do that after processing
                queue.put_nowait(new_cmd)  # Safe as queue was empty, now has one item
            except asyncio.TimeoutError:
                log.info(
                    f"Channel {channel_id} idle timeout ({settings.browser.worker_idle_timeout_sec}s) reached. Shutting down worker."
                )  # Keep as info as this is important for troubleshooting
                # If timeout occurs, the queue.get() in wait_for_new_command_task did not complete,
                # so no task_done() is needed for it. The task itself will be cancelled.
                if wait_for_new_command_task and not wait_for_new_command_task.done():
                    wait_for_new_command_task.cancel()
            except asyncio.CancelledError:
                log.info(
                    f"Channel {channel_id} idle timer wait was cancelled. Worker likely shutting down."
                )
                # If wait_for_new_command_task was cancelled, the worker should exit.
                # The outer CancelledError handler will catch this if the worker task itself is cancelled.
                # If only wait_for_new_command_task is cancelled, re-raise to stop worker.
                raise
            finally:
                # Ensure task is cancelled if it's still around and not done (e.g., if new_cmd arrived)
                if wait_for_new_command_task and not wait_for_new_command_task.done():
                    wait_for_new_command_task.cancel()
                    try:
                        await wait_for_new_command_task  # Await cancellation to settle
                    except asyncio.CancelledError:
                        pass  # Expected

    except asyncio.CancelledError:
        log.info(f"Browser worker for channel {channel_id} was cancelled. Cleaning up.")
        # Propagate cancellation if necessary or handle cleanup.
        # The finally block will execute.
    except Exception as e:
        # Catch-all for unexpected errors within the worker's main try block
        log.critical(
            f"Browser worker for channel {channel_id} encountered a critical unhandled error: {e}",
            exc_info=True,
        )
    finally:
        log.info(
            f"Worker for channel {channel_id} stopping and performing final cleanup."
        )

        if eng is not None:
            log.info(f"Closing BrowserEngine for channel {channel_id}.")
            try:
                await eng.close()
            except Exception as e_close:
                log.error(
                    f"Error closing BrowserEngine for channel {channel_id}: {e_close}",
                    exc_info=True,
                )

        # Unregister from the global browser_manager.
        # This indicates that the browser resources associated with this worker/channel_id
        # are no longer actively managed by this worker.
        try:
            await browser_manager.unregister(channel_id)
            log.info(f"Unregistered channel {channel_id} from BrowserManager.")
        except Exception as e_unreg:
            log.error(
                f"Error unregistering channel {channel_id} from BrowserManager: {e_unreg}",
                exc_info=True,
            )

        # Remove this worker's information (task and queue) from the central registry.
        await browser_worker_registry.remove_worker_info(channel_id)
        log.info(f"Worker for channel {channel_id} fully stopped and cleaned up.")
