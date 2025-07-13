"""
Circuit Breaker and Runtime Wrappers for Distributed Browser Operations
=====================================================================

Provides reliability patterns like circuit breakers, retries, and graceful
degradation for distributed browser operations. Wraps RemoteBrowserRuntime
to add production-grade reliability features.
"""

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable, TypeVar

from bot.browser.exceptions import BrowserError
from bot.core.exceptions import BotError, OperationTimeoutError, WorkerUnavailableError

from .remote_browser import RemoteBrowserRuntime

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitBreakerRuntime:
    """
    Circuit breaker wrapper for RemoteBrowserRuntime.

    Trips open after MAX_FAILS consecutive failures, staying open for COOLDOWN seconds.
    Provides fail-fast behavior instead of hanging timeouts when backend is degraded.
    """

    MAX_FAILS = 3
    COOLDOWN = 30.0  # seconds

    # Use existing bot exception hierarchy instead of custom exceptions

    def __init__(self, inner: RemoteBrowserRuntime) -> None:
        self._inner = inner
        self._fails = 0
        self._opened_until: float = 0
        self._last_error: Exception | None = None

    async def _guard(self, coro: Awaitable[T]) -> T:
        """Execute operation with circuit breaker protection."""
        # Check if circuit is open
        if self._opened_until > time.time():
            raise WorkerUnavailableError(
                f"backend (cooldown until {self._opened_until:.1f}, last error: {self._last_error})"
            )

        try:
            result = await coro
            # Success - reset failure count
            self._fails = 0
            self._last_error = None
            return result

        except Exception as exc:
            self._fails += 1
            self._last_error = exc

            # Trip circuit breaker if max failures reached
            if self._fails >= self.MAX_FAILS:
                self._opened_until = time.time() + self.COOLDOWN
                logger.warning(
                    f"Circuit breaker OPEN for {self.COOLDOWN}s after {self._fails} failures. "
                    f"Last error: {exc}"
                )

            # Re-raise with more specific exception types
            if "timeout" in str(exc).lower() or "timed out" in str(exc).lower():
                raise OperationTimeoutError(f"browser operation ({exc})") from exc
            elif "unavailable" in str(exc).lower() or "connection" in str(exc).lower():
                raise WorkerUnavailableError(f"browser workers ({exc})") from exc
            else:
                raise BrowserError(f"Browser operation failed: {exc}") from exc

    # Proxy all RemoteBrowserRuntime methods with circuit breaker protection

    async def screenshot(self, *args: Any, **kwargs: Any) -> bytes:
        return await self._guard(self._inner.screenshot(*args, **kwargs))

    async def goto(self, *args: Any, **kwargs: Any) -> Any:
        return await self._guard(self._inner.goto(*args, **kwargs))

    async def start(self, *args: Any, **kwargs: Any) -> Any:
        return await self._guard(self._inner.start(*args, **kwargs))

    async def status(self, *args: Any, **kwargs: Any) -> Any:
        return await self._guard(self._inner.status(*args, **kwargs))

    async def close_channel(self, *args: Any, **kwargs: Any) -> Any:
        return await self._guard(self._inner.close_channel(*args, **kwargs))

    async def close_all(self, *args: Any, **kwargs: Any) -> Any:
        return await self._guard(self._inner.close_all(*args, **kwargs))

    # Add any other methods from RemoteBrowserRuntime as needed

    @property
    def is_circuit_open(self) -> bool:
        """Check if circuit breaker is currently open."""
        return self._opened_until > time.time()

    @property
    def failure_count(self) -> int:
        """Current consecutive failure count."""
        return self._fails

    def reset_circuit(self) -> None:
        """Manually reset the circuit breaker (for testing/admin use)."""
        self._fails = 0
        self._opened_until = 0
        self._last_error = None
        logger.info("Circuit breaker manually reset")


class RetryableRuntime:
    """
    Retry wrapper with exponential backoff for idempotent operations.

    Useful for operations like screenshot and status that can be safely retried.
    """

    def __init__(self, inner: RemoteBrowserRuntime, max_retries: int = 2) -> None:
        self._inner = inner
        self.max_retries = max_retries

    async def _retry_with_backoff(
        self, operation: Callable[[], Awaitable[T]], operation_name: str
    ) -> T:
        """Execute operation with exponential backoff retry."""
        last_exception = None

        for attempt in range(self.max_retries + 1):
            try:
                return await operation()
            except Exception as exc:
                last_exception = exc

                if attempt < self.max_retries:
                    backoff = 2**attempt  # 1s, 2s, 4s...
                    logger.warning(
                        f"{operation_name} attempt {attempt + 1} failed: {exc}. "
                        f"Retrying in {backoff}s..."
                    )
                    await asyncio.sleep(backoff)
                else:
                    logger.error(f"{operation_name} failed after {attempt + 1} attempts")

        # Re-raise the last exception
        assert last_exception is not None
        raise last_exception

    # Only retry idempotent operations
    async def screenshot(self, *args: Any, **kwargs: Any) -> bytes:
        return await self._retry_with_backoff(
            lambda: self._inner.screenshot(*args, **kwargs), "screenshot"
        )

    async def status(self, *args: Any, **kwargs: Any) -> Any:
        return await self._retry_with_backoff(lambda: self._inner.status(*args, **kwargs), "status")

    # Non-idempotent operations pass through directly
    async def goto(self, *args: Any, **kwargs: Any) -> Any:
        return await self._inner.goto(*args, **kwargs)

    async def start(self, *args: Any, **kwargs: Any) -> Any:
        return await self._inner.start(*args, **kwargs)

    async def close_channel(self, *args: Any, **kwargs: Any) -> Any:
        return await self._inner.close_channel(*args, **kwargs)

    async def close_all(self, *args: Any, **kwargs: Any) -> Any:
        return await self._inner.close_all(*args, **kwargs)
