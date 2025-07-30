"""Base task class with thread-local event loop management."""

import asyncio
import signal
import threading
import uuid
from typing import TYPE_CHECKING, Any

from celery import Task

__all__ = ["SwarmTask"]

if TYPE_CHECKING:
    # For type checking, use the generic version
    BaseTask = Task[Any, Any]
else:
    # At runtime, use the non-generic version
    BaseTask = Task


class SwarmTask(BaseTask):
    """Base task with thread-local event loop and task ID management."""

    abstract = True

    # Thread-local storage for event loops - one loop per thread
    _thread_local = threading.local()

    def resolve_task_id(self, supplied: str | None) -> str:
        """Resolve task ID with fallback to request ID or UUID."""
        return supplied or self.request.id or str(uuid.uuid4())

    @classmethod
    def get_loop(cls) -> asyncio.AbstractEventLoop:
        """Get or create a thread-local event loop."""
        # Check if we have a loop for this thread
        loop: asyncio.AbstractEventLoop | None = getattr(cls._thread_local, "loop", None)

        # If loop exists and is not closed, return it
        if loop is not None and not loop.is_closed():
            return loop

        # Create a new event loop for this thread
        new_loop = asyncio.new_event_loop()
        cls._thread_local.loop = new_loop
        asyncio.set_event_loop(new_loop)
        return new_loop

    @classmethod
    def _close_thread_loop(cls, *_: Any) -> None:
        """Close the thread-local event loop on shutdown."""
        loop = getattr(cls._thread_local, "loop", None)
        if loop and not loop.is_closed():
            # Import here to avoid circular dependencies
            from swarm.tasks.browser import _loop_clients

            # Close any Redis client for this loop
            client = _loop_clients.pop(loop, None)
            if client is not None:
                try:
                    # Schedule the close on the loop
                    loop.run_until_complete(client.close())
                except Exception:
                    # Ignore errors during shutdown
                    pass

            # Cancel any pending tasks
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()

            # Shutdown async generators (Python 3.9+)
            if hasattr(loop, "shutdown_asyncgens"):
                loop.run_until_complete(loop.shutdown_asyncgens())

            # Stop and close the loop
            loop.call_soon_threadsafe(loop.stop)
            loop.close()


# Register SIGTERM/SIGINT handlers so each worker thread
# closes its own event loop cleanly during warm shutdown.
# This prevents "event loop is closed" errors on worker restart.
try:
    # Only register signal handlers from the main thread
    if threading.current_thread() is threading.main_thread():
        # Handle both SIGTERM (production) and SIGINT (local debugging)
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, SwarmTask._close_thread_loop)
            except (OSError, ValueError):
                # Signal might not be valid on this platform
                pass
except (ImportError, AttributeError):
    # Non-POSIX platform (e.g., Windows) - no graceful loop close on signals
    pass
