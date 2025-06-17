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
from typing import Any, Callable, TypeVar

__all__ = ["run_in_threadpool"]

T = TypeVar("T")


def run_in_threadpool(
    func: Callable[..., T], *args: Any, **kwargs: Any
) -> "asyncio.Future[T]":
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
