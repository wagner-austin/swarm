from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Dict, Any, TypeVar  # Using Any for asyncio.Task generic type

# Assuming Command is already defined in command.py
from bot.core.api.browser.command import Command

_T = TypeVar("_T")

# TODO: Consider adding asyncio.Lock to protect _active_worker_tasks and _queues
# if accessed concurrently from different event loop tasks in a way that could cause race conditions.
# For now, assuming operations are serialized correctly by the event loop context they run in.

log = logging.getLogger(__name__)

__all__ = ["BrowserWorkerRegistry", "browser_worker_registry"]


class BrowserWorkerRegistry:
    def __init__(self) -> None:
        self._active_worker_tasks: Dict[int, asyncio.Task[Any]] = {}
        self._command_queues: Dict[int, asyncio.Queue[Command | object]] = defaultdict(
            lambda: asyncio.Queue(maxsize=100)
        )  # Added maxsize for safety
        self._lock = asyncio.Lock()

    async def get_or_create_queue(
        self, channel_id: int
    ) -> asyncio.Queue[Command | object]:
        """Gets or creates a command queue for the given channel ID."""
        async with self._lock:
            # Ensure queue is created if it doesn't exist while under lock
            if channel_id not in self._command_queues:
                self._command_queues[channel_id] = asyncio.Queue(maxsize=100)
            return self._command_queues[channel_id]

    async def add_worker_task(self, channel_id: int, task: asyncio.Task[Any]) -> None:
        """Adds a worker task to the registry."""
        async with self._lock:
            if (
                channel_id in self._active_worker_tasks
                and not self._active_worker_tasks[channel_id].done()
            ):
                raise RuntimeError(
                    f"Attempted to start duplicate worker for channel {channel_id}"
                )
            self._active_worker_tasks[channel_id] = task
            log.info(f"Added worker task for channel {channel_id} to registry.")

    async def is_worker_active(self, channel_id: int) -> bool:
        """Checks if a worker task is active for the given channel ID."""
        async with self._lock:
            task = self._active_worker_tasks.get(channel_id)
            return bool(task and not task.done())

    async def get_worker_task(self, channel_id: int) -> asyncio.Task[Any] | None:
        """Gets the worker task for the given channel ID, if it exists."""
        async with self._lock:
            return self._active_worker_tasks.get(channel_id)

    async def remove_worker_info(self, channel_id: int) -> None:
        """
        Removes worker task and its associated queue from the registry.
        This should be called when a worker shuts down or fails.
        Protected by an asyncio.Lock.
        """
        async with self._lock:
            task = self._active_worker_tasks.pop(channel_id, None)
            if task:
                log.info(f"Removed worker task for channel {channel_id} from registry.")
            else:
                log.warning(
                    f"Attempted to remove worker info for non-existent task for channel {channel_id}."
                )

            queue = self._command_queues.get(channel_id)
            if queue:
                if queue.empty():
                    log.info(
                        f"Command queue for channel {channel_id} is empty. Removing from registry."
                    )
                    if channel_id in self._command_queues:  # Check before deleting
                        del self._command_queues[channel_id]
                else:
                    log.warning(
                        f"Queue for channel {channel_id} is not empty during worker removal. "
                        f"{queue.qsize()} items remaining. Draining and removing queue to prevent leaks."
                    )
                    while not queue.empty():
                        try:
                            cmd = queue.get_nowait()
                            # Safely handle cmd which could be None (sentinel) or a Command dict
                            if (
                                cmd is not None
                                and isinstance(cmd, dict)
                                and cmd.get("future")
                                and not cmd["future"].done()
                            ):
                                cmd["future"].set_exception(
                                    RuntimeError(
                                        "Worker shut down before processing this command."
                                    )
                                )
                            queue.task_done()  # Ensure task_done is called for drained items
                        except asyncio.QueueEmpty:
                            break
                        except Exception as e_drain:
                            log.error(
                                f"Error draining command from queue for channel {channel_id}: {e_drain}"
                            )
                            break
                    if channel_id in self._command_queues:  # Check before deleting
                        del self._command_queues[channel_id]
            else:
                log.debug(
                    f"No command queue found for channel {channel_id} during worker info removal."
                )


# Singleton instance
# The type: ignore[call-arg] is needed because mypy struggles with defaultdict
# and a lambda function that creates a Queue if BrowserWorkerRegistry were generic.
# Since BrowserWorkerRegistry is not generic, this specific instantiation is fine.
browser_worker_registry = BrowserWorkerRegistry()
