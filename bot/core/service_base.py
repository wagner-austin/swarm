"""Common lifecycle interface for long-running background services.

Every service that needs explicit *start/stop* control (proxy, TankPit engine,
browser engine, etc.) should implement this protocol.  Having a shared contract
lets orchestrators (e.g. :pymod:`bot.core.lifecycle`) manage heterogeneous
services with uniform logic and enables stricter static-type checking.
"""

from __future__ import annotations

import abc
from typing import Protocol, runtime_checkable

__all__ = ["ServiceABC"]


@runtime_checkable
class ServiceABC(Protocol):
    """Async lifecycle contract for background services."""

    # ------------------------------------------------------------------+
    # Required methods                                                  |
    # ------------------------------------------------------------------+

    async def start(self) -> None:  # noqa: D401 (imperative)
        """Bring the service to a *running* state.

        The call *must* be idempotent – calling ``start`` on an already running
        instance should be a no-op (or raise a well-documented exception).
        """

    async def stop(self, *, graceful: bool = True) -> None:  # noqa: D401
        """Transition the service to a *stopped* state.

        Parameters
        ----------
        graceful:
            When *True* the service should finish in-flight work; when *False*
            an immediate/cancel-pending shutdown is acceptable.
        """

    # ------------------------------------------------------------------+
    # Optional helpers – not strictly required by every implementation  |
    # ------------------------------------------------------------------+

    def is_running(self) -> bool:  # pragma: no cover – default impl below
        """Return *True* if the service believes itself to be running."""
        raise NotImplementedError

    def describe(self) -> str:  # pragma: no cover – default impl below
        """Human-readable one-line status summary for UIs or logs."""
        return "running" if self.is_running() else "stopped"


class AbstractService(ServiceABC, abc.ABC):
    """Convenience ABC providing default *describe* implementation."""

    _running: bool = False  # subclasses should maintain this flag

    async def start(self) -> None:  # pragma: no cover – abstract
        self._running = True

    async def stop(self, *, graceful: bool = True) -> None:  # pragma: no cover – abstract
        self._running = False

    def is_running(self) -> bool:
        return self._running

    def describe(self) -> str:
        return super().describe()
