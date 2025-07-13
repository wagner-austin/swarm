"""
Fake Browser Runtime for Testing
=================================

Provides a fake implementation of RemoteBrowserRuntime that doesn't require
actual worker infrastructure, enabling fast and reliable unit tests.
"""

import asyncio
from typing import Any, Awaitable, Callable, TypeVar

from bot.distributed.remote_browser import RemoteBrowserRuntime

T = TypeVar("T")


class FakeBrowserRuntime:
    """
    Fake browser runtime that simulates RemoteBrowserRuntime behavior
    without requiring actual workers or Redis infrastructure.
    """

    def __init__(self, should_fail: bool = False, fail_message: str = "Simulated failure") -> None:
        self.should_fail = should_fail
        self.fail_message = fail_message
        self.call_history: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def _record_call(self, method_name: str, *args: Any, **kwargs: Any) -> None:
        """Record method calls for test verification."""
        self.call_history.append((method_name, args, kwargs))

    async def goto(self, url: str, *, worker_hint: str | None = None) -> None:
        """Simulate navigating to a URL."""
        self._record_call("goto", url, worker_hint=worker_hint)
        if self.should_fail:
            raise RuntimeError(self.fail_message)
        await asyncio.sleep(0.01)  # Simulate async operation

    async def start(self, worker_hint: str | None = None) -> None:
        """Simulate starting a browser session."""
        self._record_call("start", worker_hint=worker_hint)
        if self.should_fail:
            raise RuntimeError(self.fail_message)
        await asyncio.sleep(0.01)

    async def screenshot(
        self, filename: str | None = None, *, worker_hint: str | None = None
    ) -> bytes:
        """Simulate taking a screenshot, returns fake PNG data."""
        self._record_call("screenshot", filename, worker_hint=worker_hint)
        if self.should_fail:
            raise RuntimeError(self.fail_message)

        await asyncio.sleep(0.01)

        # Return minimal valid PNG header
        return b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x00\x00\x00\x01\x00\x01U\xaa\x00\x05\x00\x00\x00\x00IEND\xaeB`\x82"

    async def status(self, *, worker_hint: str | None = None) -> dict[str, Any]:
        """Simulate getting browser status."""
        self._record_call("status", worker_hint=worker_hint)
        if self.should_fail:
            raise RuntimeError(self.fail_message)

        await asyncio.sleep(0.01)
        return {"worker_id": "fake-worker", "status": "healthy", "sessions": 0, "uptime": 100.0}

    async def close_channel(self, channel_id: int, *, worker_hint: str | None = None) -> None:
        """Simulate closing a channel's browser session."""
        self._record_call("close_channel", channel_id, worker_hint=worker_hint)
        if self.should_fail:
            raise RuntimeError(self.fail_message)
        await asyncio.sleep(0.01)

    async def close_all(self, *, worker_hint: str | None = None) -> None:
        """Simulate closing all browser sessions."""
        self._record_call("close_all", worker_hint=worker_hint)
        if self.should_fail:
            raise RuntimeError(self.fail_message)
        await asyncio.sleep(0.01)

    def was_called(self, method_name: str) -> bool:
        """Check if a method was called during testing."""
        return any(call[0] == method_name for call in self.call_history)

    def get_call_args(self, method_name: str) -> tuple[tuple[Any, ...], dict[str, Any]] | None:
        """Get the arguments from the last call to a method."""
        for call in reversed(self.call_history):
            if call[0] == method_name:
                return call[1], call[2]
        return None

    def reset_history(self) -> None:
        """Clear call history for fresh test state."""
        self.call_history.clear()


class FakeCircuitBreakerRuntime(FakeBrowserRuntime):
    """
    Fake circuit breaker runtime that simulates circuit breaker behavior
    for testing failure scenarios.
    """

    def __init__(self, max_fails: int = 3, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.max_fails = max_fails
        self.fail_count = 0
        self.circuit_open = False

    async def _execute_with_circuit_breaker(
        self, method_name: str, coro_func: Callable[[], Awaitable[T]]
    ) -> T:
        """Execute method with circuit breaker simulation."""
        if self.circuit_open:
            from bot.core.exceptions import WorkerUnavailableError

            raise WorkerUnavailableError("Circuit breaker is open")

        try:
            result = await coro_func()
            self.fail_count = 0  # Reset on success
            return result
        except Exception as exc:
            self.fail_count += 1
            if self.fail_count >= self.max_fails:
                self.circuit_open = True
            raise exc

    async def screenshot(self, *args: Any, **kwargs: Any) -> bytes:
        """Screenshot with circuit breaker protection."""

        async def _screenshot() -> bytes:
            return await FakeBrowserRuntime.screenshot(self, *args, **kwargs)

        return await self._execute_with_circuit_breaker("screenshot", _screenshot)

    async def goto(self, *args: Any, **kwargs: Any) -> None:
        """Goto with circuit breaker protection."""

        async def _goto() -> None:
            return await FakeBrowserRuntime.goto(self, *args, **kwargs)

        return await self._execute_with_circuit_breaker("goto", _goto)

    def reset_circuit(self) -> None:
        """Reset circuit breaker for testing."""
        self.fail_count = 0
        self.circuit_open = False
