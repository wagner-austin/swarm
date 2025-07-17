"""Cross-platform helper to install OS signal handlers on an asyncio loop.

The swarm registers a few UNIX-style signals (``SIGINT``, ``SIGTERM``) so it can
shut down gracefully when the user presses *Ctrl+C* or the process manager
sends a termination request.  The registration logic used to be open-coded in
``swarm.core.launcher`` and is now extracted into this small utility to make it
re-usable from other CLI entry points and easier to unit-test.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from collections.abc import Iterable
from typing import Any, cast

logger = logging.getLogger(__name__)

__all__ = [
    "install_handlers",
    "SignalHandlers",
]


def install_handlers(
    loop: asyncio.AbstractEventLoop,
    manager: asyncio.Future[Any] | object,
    *,
    signals: Iterable[signal.Signals] | None = None,
) -> list[signal.Signals]:
    """Register *signals* on *loop* and forward them to *manager.shutdown()*.

    Parameters
    ----------
    loop:
        The running asyncio event loop.  Typically obtained via
        ``asyncio.get_running_loop()``.
    manager:
        An object that exposes an async ``shutdown(*, signal_name: str)``
        coroutine – for the swarm this is :class:`swarm.core.lifecycle.SwarmLifecycle`.
    signals:
        Optional iterable of :class:`signal.Signals` to hook up.  When *None*, a
        platform-appropriate default is used (``SIGINT`` + ``SIGTERM`` on
        POSIX, only ``SIGINT`` on Windows).

    Returns
    -------
    list[signal.Signals]
        The list of signals that were successfully installed.  The caller can
        later iterate over this to remove the handlers for a clean test tear-down.
    """

    if signals is None:
        sigs: list[signal.Signals] = [signal.SIGINT]
        if os.name != "nt":  # SIGTERM is a no-op on Windows consoles
            sigs.append(signal.SIGTERM)
    else:
        sigs = list(signals)

    from collections.abc import Callable

    def _make_handler(sig_to_use: signal.Signals) -> Callable[[], None]:
        def _handler() -> None:  # pragma: no cover – real signal path
            logger.info("Received signal %s, initiating graceful shutdown…", sig_to_use.name)
            # Fire-and-forget – the event loop keeps running until shutdown completes
            asyncio.create_task(cast(Any, manager).shutdown(signal_name=sig_to_use.name))

        return _handler

    installed: list[signal.Signals] = []
    for sig in sigs:
        try:
            loop.add_signal_handler(sig, _make_handler(sig))
            logger.debug("Registered handler for %s", sig.name)
            installed.append(sig)
        except (NotImplementedError, AttributeError, ValueError, RuntimeError) as e:
            logger.warning("Could not set %s handler: %s", sig.name, e)

    return installed


class SignalHandlers:
    """Async context-manager that installs OS signal handlers and cleans up automatically."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        manager: asyncio.Future[Any] | object,
        *,
        signals: Iterable[signal.Signals] | None = None,
    ) -> None:
        self._loop = loop
        self._manager = manager
        self._signals = signals
        self._installed: list[signal.Signals] = []

    async def __aenter__(self) -> SignalHandlers:  # noqa: D401 – context manager
        self._installed = install_handlers(self._loop, self._manager, signals=self._signals)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: Any | None,
    ) -> bool:
        for sig in self._installed:
            try:
                self._loop.remove_signal_handler(sig)
                logger.debug("Removed signal handler for %s", sig.name)
            except (
                NotImplementedError,
                AttributeError,
                ValueError,
                RuntimeError,
            ) as e:  # pragma: no cover
                logger.debug("Could not remove %s handler during cleanup: %s", sig.name, e)
        # Do not suppress exceptions
        return False
