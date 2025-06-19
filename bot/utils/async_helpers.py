"""Utility helpers for running blocking callables in a thread pool.

This module provides a thin wrapper around ``asyncio.loop.run_in_executor``
so that synchronous / CPU-heavy functions can be executed without blocking the
asyncio event-loop.  Using the **default** executor is sufficient for most
Discord-bot workloads – if you need fine-grained control (e.g. a dedicated
``ThreadPoolExecutor``), extend this helper or call the low-level API directly.
"""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

__all__ = ["run_in_threadpool", "with_retries"]

T = TypeVar("T")


async def with_retries(
    coro_factory: Callable[[], Awaitable[T]],
    max_tries: int,
    initial_delay: float,
    *,
    backoff: float = 2.0,
) -> T:
    """Run *coro_factory* with exponential back-off until it succeeds or retries are exhausted.

    Parameters
    ----------
    coro_factory:
        Zero-arg callable returning an awaitable.  A *new* coroutine/awaitable **must** be
        created on each call – so pass a *factory*, not the coroutine itself.
    max_tries:
        Total attempts (initial call counts as 1).
    initial_delay:
        Delay **before** the first retry attempt (in seconds).
    backoff:
        Multiplier applied to the delay after each failed attempt.  Defaults to *2.0*.

    Returns
    -------
    The awaited result of *coro_factory* on the first successful attempt.

    Raises
    ------
    Exception
        Re-raises the *last* encountered exception if all attempts fail.
    """
    attempt = 0
    delay = initial_delay
    while True:
        try:
            return await coro_factory()
        except Exception:
            attempt += 1
            if attempt >= max_tries:
                raise
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                # Propagate cancellations immediately to respect shutdown signals.
                raise
            delay *= backoff


def run_in_threadpool(func: Callable[..., T], *args: Any, **kwargs: Any) -> asyncio.Future[T]:
    """Run *func* in the event-loop's default thread-pool executor.

    Example
    -------
    >>> content = await run_in_threadpool(path.read_bytes)
    >>> data = await run_in_threadpool(requests.get, url, timeout=5)

    The returned awaitable resolves to the function's return value.
    """
    loop = asyncio.get_running_loop()
    partial_func: Callable[[], T] = functools.partial(func, *args, **kwargs)
    return loop.run_in_executor(None, partial_func)
