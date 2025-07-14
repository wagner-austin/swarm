"""
Tests for Worker Pool Management
=================================

Tests the WorkerPool class using real objects, no mocks.
"""

import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from bot.distributed.core.pool import WorkerInfo, WorkerPool


class TestWorkerInfo:
    """Test the WorkerInfo dataclass."""

    def test_worker_info_creation(self) -> None:
        """Test creating a worker info object."""
        worker = WorkerInfo(
            id="test-worker-1",
            capabilities={"type": "browser", "max_sessions": 5},
        )

        assert worker.id == "test-worker-1"
        assert worker.capabilities["type"] == "browser"
        assert worker.status == "healthy"
        assert worker.jobs_completed == 0
        assert worker.jobs_failed == 0
        assert worker.registered_at > 0
        assert worker.last_heartbeat > 0

    def test_is_healthy_fresh_worker(self) -> None:
        """Test that a fresh worker is healthy."""
        worker = WorkerInfo(id="test-1", capabilities={})
        assert worker.is_healthy(timeout=60.0)

    def test_is_healthy_stale_worker(self) -> None:
        """Test that a stale worker is not healthy."""
        worker = WorkerInfo(id="test-1", capabilities={})
        # Manually set old heartbeat
        worker.last_heartbeat = time.time() - 120  # 2 minutes ago
        assert not worker.is_healthy(timeout=60.0)

    def test_is_healthy_unhealthy_status(self) -> None:
        """Test that unhealthy status makes worker unhealthy."""
        worker = WorkerInfo(id="test-1", capabilities={})
        worker.status = "unhealthy: connection lost"
        assert not worker.is_healthy(timeout=60.0)


class TestWorkerPool:
    """Test the WorkerPool class."""

    def test_pool_creation(self) -> None:
        """Test creating a worker pool."""
        pool = WorkerPool("browser", health_timeout=30.0)
        assert pool.worker_type == "browser"
        assert pool.health_timeout == 30.0
        assert len(pool.workers) == 0
        assert len(pool) == 0  # __len__ returns healthy count

    def test_register_new_worker(self) -> None:
        """Test registering a new worker."""
        pool = WorkerPool("browser")

        pool.register_worker("worker-1", {"max_sessions": 3})

        assert len(pool.workers) == 1
        assert "worker-1" in pool.workers
        assert pool.workers["worker-1"].capabilities["max_sessions"] == 3
        assert pool.workers["worker-1"].status == "healthy"

    def test_register_existing_worker_updates(self) -> None:
        """Test that re-registering updates the worker."""
        pool = WorkerPool("browser")

        # Initial registration
        pool.register_worker("worker-1", {"max_sessions": 3})
        original_time = pool.workers["worker-1"].registered_at

        # Wait a bit and re-register
        time.sleep(0.01)
        pool.register_worker("worker-1", {"max_sessions": 5})

        # Should update capabilities but not registration time
        assert pool.workers["worker-1"].capabilities["max_sessions"] == 5
        assert pool.workers["worker-1"].registered_at == original_time
        assert pool.workers["worker-1"].last_heartbeat > original_time

    def test_mark_healthy_unhealthy(self) -> None:
        """Test marking workers healthy/unhealthy."""
        pool = WorkerPool("browser")
        pool.register_worker("worker-1", {})

        # Mark unhealthy
        pool.mark_unhealthy("worker-1", "test failure")
        assert pool.workers["worker-1"].status == "unhealthy: test failure"

        # Mark healthy again
        pool.mark_healthy("worker-1")
        assert pool.workers["worker-1"].status == "healthy"

    def test_record_job_statistics(self) -> None:
        """Test recording job completion/failure."""
        pool = WorkerPool("browser")
        pool.register_worker("worker-1", {})

        # Record some completions and failures
        pool.record_job_completed("worker-1")
        pool.record_job_completed("worker-1")
        pool.record_job_failed("worker-1")

        worker = pool.workers["worker-1"]
        assert worker.jobs_completed == 2
        assert worker.jobs_failed == 1

    def test_get_healthy_workers(self) -> None:
        """Test getting only healthy workers."""
        pool = WorkerPool("browser", health_timeout=0.1)

        # Register 3 workers
        pool.register_worker("worker-1", {})
        pool.register_worker("worker-2", {})
        pool.register_worker("worker-3", {})

        # Make one unhealthy by status
        pool.mark_unhealthy("worker-2", "test")

        # Make one unhealthy by staleness
        pool.workers["worker-3"].last_heartbeat = time.time() - 1.0

        healthy = pool.get_healthy_workers()
        assert len(healthy) == 1
        assert healthy[0].id == "worker-1"

    def test_get_worker_ids(self) -> None:
        """Test getting worker IDs."""
        pool = WorkerPool("browser")
        pool.register_worker("worker-1", {})
        pool.register_worker("worker-2", {})
        pool.mark_unhealthy("worker-2", "test")

        # Get all IDs
        all_ids = pool.get_worker_ids(only_healthy=False)
        assert set(all_ids) == {"worker-1", "worker-2"}

        # Get only healthy IDs
        healthy_ids = pool.get_worker_ids(only_healthy=True)
        assert healthy_ids == ["worker-1"]

    def test_remove_stale_workers(self) -> None:
        """Test removing stale workers."""
        pool = WorkerPool("browser", health_timeout=0.1)

        # Register workers
        pool.register_worker("worker-1", {})
        pool.register_worker("worker-2", {})
        pool.register_worker("worker-3", {})

        # Make some stale
        pool.workers["worker-1"].last_heartbeat = time.time() - 1.0
        pool.workers["worker-2"].status = "unhealthy: test"

        # Remove stale workers
        removed = pool.remove_stale_workers()

        # Should remove worker-1 (stale heartbeat) and worker-2 (unhealthy)
        assert set(removed) == {"worker-1", "worker-2"}
        assert len(pool.workers) == 1
        assert "worker-3" in pool.workers

    def test_get_statistics(self) -> None:
        """Test getting pool statistics."""
        pool = WorkerPool("browser")

        # Register workers with some job history
        pool.register_worker("worker-1", {})
        pool.record_job_completed("worker-1")
        pool.record_job_completed("worker-1")

        pool.register_worker("worker-2", {})
        pool.record_job_completed("worker-2")
        pool.record_job_failed("worker-2")

        stats = pool.get_statistics()

        assert stats["worker_type"] == "browser"
        assert stats["total_workers"] == 2
        assert stats["healthy_workers"] == 2
        assert stats["unhealthy_workers"] == 0
        assert stats["total_jobs_completed"] == 3
        assert stats["total_jobs_failed"] == 1
        assert stats["success_rate"] == 0.75

    def test_statistics_with_no_jobs(self) -> None:
        """Test statistics when no jobs have been processed."""
        pool = WorkerPool("browser")
        pool.register_worker("worker-1", {})

        stats = pool.get_statistics()
        assert stats["total_jobs_completed"] == 0
        assert stats["total_jobs_failed"] == 0
        assert stats["success_rate"] == 0.0  # Should not divide by zero

    def test_len_returns_healthy_count(self) -> None:
        """Test that len() returns healthy worker count."""
        pool = WorkerPool("browser")

        pool.register_worker("worker-1", {})
        pool.register_worker("worker-2", {})
        pool.mark_unhealthy("worker-2", "test")

        assert len(pool) == 1  # Only healthy workers

    def test_repr(self) -> None:
        """Test string representation."""
        pool = WorkerPool("tankpit")
        pool.register_worker("worker-1", {})
        pool.register_worker("worker-2", {})
        pool.mark_unhealthy("worker-2", "test")

        repr_str = repr(pool)
        assert "WorkerPool" in repr_str
        assert "type=tankpit" in repr_str
        assert "healthy=1" in repr_str
        assert "total=2" in repr_str
