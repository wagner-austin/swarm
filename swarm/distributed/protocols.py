"""
Protocols for Distributed Components
====================================

Defines protocols (interfaces) for distributed system components.
This allows for pluggable implementations without tight coupling.
"""

from enum import Enum
from typing import Protocol, runtime_checkable


class ScalingDecision(Enum):
    """Decision made by the scaling algorithm."""

    SCALE_UP = "scale_up"
    SCALE_DOWN = "scale_down"
    NO_CHANGE = "no_change"


@runtime_checkable
class ScalingBackend(Protocol):
    """
    Protocol for scaling backend implementations.

    Defines the interface that all scaling backends must implement,
    whether Docker, Kubernetes, Fly.io, or other orchestrators.
    """

    async def scale_to(self, worker_type: str, target_count: int) -> bool:
        """
        Scale a worker type to the target count.

        Args:
            worker_type: Type of worker (e.g., "browser", "tankpit")
            target_count: Desired number of workers

        Returns:
            True if scaling succeeded, False otherwise
        """
        ...

    async def get_current_count(self, worker_type: str) -> int:
        """
        Get the current number of workers of a given type.

        Args:
            worker_type: Type of worker to check

        Returns:
            Current number of running workers
        """
        ...
