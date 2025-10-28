"""Base task class with thread-local event loop management."""

import asyncio
import signal
import threading
import uuid
from typing import TYPE_CHECKING, Generic, ParamSpec, Protocol, TypeVar

from celery import Task as CeleryTask

__all__ = ["SwarmTask"]

_P = ParamSpec("_P")
_R = TypeVar("_R")


# Use TYPE_CHECKING pattern to handle stub vs runtime mismatch
# - Stub declares Task as Generic[_P, _R], but runtime Task is not subscriptable
# - The actual strict typing comes from Generic[_P, _R] on SwarmTask class below
# Solution from: https://mypy.readthedocs.io/en/stable/runtime_troubles.html
# and https://github.com/sbdchd/celery-types/issues/80
class _RequestProto(Protocol):
    id: str


class _SwarmTaskLoopMixin(Generic[_P, _R]):
    """Thread-local loop and id resolution helpers for tasks."""

    abstract = True

    # Celery provides `request` with an `id` attribute; annotate for type-checking
    request: _RequestProto

    # Thread-local storage for event loops - one loop per thread
    _thread_local = threading.local()

    def resolve_session_id(self, supplied: str | None) -> str:
        """Resolve session ID with strict fallback to Celery request ID.

        Args:
            supplied: Optional explicit session ID

        Returns:
            Session ID (supplied or from request.id)

        Raises:
            RuntimeError: If session_id not provided and self.request.id unavailable
        """
        if supplied:
            return supplied

        request_id = self.request.id
        if not request_id:
            import logging

            logger = logging.getLogger(__name__)
            logger.error(
                f"CRITICAL: self.request.id is falsy ({repr(request_id)}) in task. "
                f"This should never happen. Request: {self.request}"
            )
            raise RuntimeError(
                f"session_id not provided and self.request.id is unavailable ({repr(request_id)}). "
                "This indicates a serious bug in Celery task initialization."
            )

        return request_id

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
    def _close_thread_loop(cls, *_: object) -> None:
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


if TYPE_CHECKING:

    class SwarmTask(CeleryTask[_P, _R], Generic[_P, _R]):
        """Typed task base for type-checkers only."""

        _thread_local: object

        @classmethod
        def get_loop(cls) -> asyncio.AbstractEventLoop: ...
        @classmethod
        def _close_thread_loop(cls, *_: object) -> None: ...
        def resolve_session_id(self, supplied: str | None) -> str: ...
else:

    class SwarmTask(CeleryTask, _SwarmTaskLoopMixin[_P, _R], Generic[_P, _R]):
        """Runtime task base with loop management."""

        pass


# Register SIGTERM/SIGINT handlers so each worker thread closes its own event
# loop cleanly during warm shutdown. Prevents "event loop is closed" on restart.
try:
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, SwarmTask._close_thread_loop)
            except (OSError, ValueError):
                pass
except (ImportError, AttributeError):
    pass
