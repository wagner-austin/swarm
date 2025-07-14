"""
Fake Scaling Backend for Testing
=================================

Provides a fake implementation of the scaling backend protocol
for testing the scaling service without actually spawning containers.
"""

from typing import Dict, List, Tuple


class FakeScalingBackend:
    """
    Fake scaling backend that simulates container orchestration.

    This fake:
    - Tracks worker counts in memory
    - Records all scaling operations
    - Can simulate failures
    """

    def __init__(self, initial_counts: dict[str, int] | None = None):
        self.worker_counts: dict[str, int] = initial_counts or {}
        self.scaling_history: list[tuple[str, int, int]] = []
        self.should_fail = False
        self.fail_message = "Simulated scaling failure"

    async def scale_to(self, worker_type: str, target_count: int) -> bool:
        """Scale worker type to target count."""
        if self.should_fail:
            return False

        current = self.worker_counts.get(worker_type, 0)
        self.worker_counts[worker_type] = target_count
        self.scaling_history.append((worker_type, current, target_count))
        return True

    async def get_current_count(self, worker_type: str) -> int:
        """Get current number of workers."""
        return self.worker_counts.get(worker_type, 0)

    def set_count(self, worker_type: str, count: int) -> None:
        """Manually set worker count for testing."""
        self.worker_counts[worker_type] = count

    def get_scaling_history(self) -> list[tuple[str, int, int]]:
        """Get history of scaling operations."""
        return self.scaling_history.copy()

    def clear_history(self) -> None:
        """Clear scaling history."""
        self.scaling_history.clear()

    def get_last_scaling(self) -> tuple[str, int, int] | None:
        """Get the last scaling operation."""
        return self.scaling_history[-1] if self.scaling_history else None

    def was_scaled(self, worker_type: str) -> bool:
        """Check if a worker type was scaled."""
        return any(op[0] == worker_type for op in self.scaling_history)
