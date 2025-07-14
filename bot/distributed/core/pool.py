"""
Worker Pool Management
======================

Manages pools of workers with health tracking and capability discovery.
This is a core data structure used by the orchestrator and other services.
"""

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class WorkerInfo:
    """Information about a single worker."""

    id: str
    capabilities: dict[str, Any]
    status: str = "healthy"
    jobs_completed: int = 0
    jobs_failed: int = 0
    registered_at: float = field(default_factory=time.time)
    last_heartbeat: float = field(default_factory=time.time)

    def is_healthy(self, timeout: float = 60.0) -> bool:
        """Check if worker is still healthy based on heartbeat."""
        return self.status == "healthy" and time.time() - self.last_heartbeat < timeout


class WorkerPool:
    """
    Manages a pool of workers with health tracking.

    This class is responsible for:
    - Tracking worker registration and health
    - Managing worker lifecycle
    - Providing worker statistics
    """

    def __init__(self, worker_type: str, health_timeout: float = 60.0):
        self.worker_type = worker_type
        self.health_timeout = health_timeout
        self.workers: dict[str, WorkerInfo] = {}

    def register_worker(self, worker_id: str, capabilities: dict[str, Any]) -> None:
        """Register a new worker or update existing."""
        if worker_id in self.workers:
            # Update existing worker
            self.workers[worker_id].capabilities = capabilities
            self.workers[worker_id].last_heartbeat = time.time()
            self.workers[worker_id].status = "healthy"
        else:
            # New worker
            self.workers[worker_id] = WorkerInfo(
                id=worker_id,
                capabilities=capabilities,
            )

    def mark_healthy(self, worker_id: str) -> None:
        """Mark worker as healthy and update heartbeat."""
        if worker_id in self.workers:
            self.workers[worker_id].status = "healthy"
            self.workers[worker_id].last_heartbeat = time.time()

    def mark_unhealthy(self, worker_id: str, reason: str = "unknown") -> None:
        """Mark worker as unhealthy."""
        if worker_id in self.workers:
            self.workers[worker_id].status = f"unhealthy: {reason}"

    def record_job_completed(self, worker_id: str) -> None:
        """Record successful job completion."""
        if worker_id in self.workers:
            self.workers[worker_id].jobs_completed += 1

    def record_job_failed(self, worker_id: str) -> None:
        """Record failed job."""
        if worker_id in self.workers:
            self.workers[worker_id].jobs_failed += 1

    def get_healthy_workers(self) -> list[WorkerInfo]:
        """Get list of healthy workers."""
        return [
            worker for worker in self.workers.values() if worker.is_healthy(self.health_timeout)
        ]

    def get_worker_ids(self, only_healthy: bool = True) -> list[str]:
        """Get list of worker IDs."""
        if only_healthy:
            return [w.id for w in self.get_healthy_workers()]
        return list(self.workers.keys())

    def remove_stale_workers(self) -> list[str]:
        """Remove workers that haven't sent heartbeat recently."""
        removed = []

        for worker_id in list(self.workers.keys()):
            worker = self.workers[worker_id]
            if not worker.is_healthy(self.health_timeout):
                del self.workers[worker_id]
                removed.append(worker_id)

        return removed

    def get_statistics(self) -> dict[str, Any]:
        """Get pool statistics."""
        healthy_workers = self.get_healthy_workers()
        total_jobs_completed = sum(w.jobs_completed for w in self.workers.values())
        total_jobs_failed = sum(w.jobs_failed for w in self.workers.values())

        return {
            "worker_type": self.worker_type,
            "total_workers": len(self.workers),
            "healthy_workers": len(healthy_workers),
            "unhealthy_workers": len(self.workers) - len(healthy_workers),
            "total_jobs_completed": total_jobs_completed,
            "total_jobs_failed": total_jobs_failed,
            "success_rate": (
                total_jobs_completed / (total_jobs_completed + total_jobs_failed)
                if (total_jobs_completed + total_jobs_failed) > 0
                else 0.0
            ),
        }

    def __len__(self) -> int:
        """Return number of healthy workers."""
        return len(self.get_healthy_workers())

    def __repr__(self) -> str:
        """Return string representation of the worker pool."""
        return (
            f"WorkerPool(type={self.worker_type}, "
            f"healthy={len(self.get_healthy_workers())}, "
            f"total={len(self.workers)})"
        )
