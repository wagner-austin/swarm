"""Worker registry for querying and managing worker information."""

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, TypedDict

import redis

from swarm.core.settings import Settings

if TYPE_CHECKING:
    # For type checking, Redis client type
    RedisSyncClient = redis.Redis
else:
    # At runtime, Redis is not generic
    RedisSyncClient = redis.Redis

from swarm.infra.redis_protocols import RedisSyncProtocol, wrap_redis_sync

logger = logging.getLogger(__name__)


@dataclass
class WorkerInfo:
    """Information about a registered worker."""

    worker_id: str
    hostname: str
    capabilities: list[str]
    status: str
    current_sessions: int
    max_sessions: int
    started_at: datetime
    last_heartbeat: datetime
    platform: str
    python_version: str
    load_percentage: float  # current_sessions / max_sessions * 100


class WorkerRegistry:
    """Query and manage worker information."""

    def __init__(self, redis_client: RedisSyncProtocol | None = None):
        """Initialize worker registry.

        Args:
            redis_client: Redis client instance (uses default if not provided)
        """
        settings = Settings()
        if not settings.redis.url:
            raise ValueError("Redis URL not configured")

        if redis_client is not None:
            self.redis: RedisSyncProtocol = redis_client
        else:
            self.redis = wrap_redis_sync(redis.from_url(settings.redis.url, decode_responses=True))

    def get_all_workers(self) -> list[WorkerInfo]:
        """Get all registered workers (healthy and unhealthy).

        Returns:
            List of WorkerInfo objects
        """
        workers = []

        try:
            # Find all worker keys
            worker_keys = self.redis.keys("browser:worker:*")

            for key in worker_keys:
                worker_data = self.redis.hgetall(key)
                if worker_data:
                    worker_info = self._parse_worker_data(worker_data)
                    if worker_info:
                        workers.append(worker_info)

        except Exception as e:
            logger.error(f"Failed to get all workers: {e}")

        return workers

    def get_healthy_workers(self, capability: str | None = None) -> list[WorkerInfo]:
        """Get list of healthy workers with optional capability filter.

        A worker is considered healthy if its standardized heartbeat timestamp is fresh.

        Args:
            capability: Optional capability to filter by (e.g., "browser", "gpu")

        Returns:
            List of healthy WorkerInfo objects
        """
        all_workers = self.get_all_workers()
        healthy_workers = []

        for worker in all_workers:
            # Authoritative liveness from heartbeat timestamp freshness
            hb_key = f"worker:heartbeat:browser:{worker.worker_id}"
            ts_raw = self.redis.hget(hb_key, "timestamp")
            is_alive = False
            try:
                if ts_raw:
                    ts = float(ts_raw)
                    is_alive = (time.time() - ts) <= 90.0
            except Exception:
                is_alive = False
            if is_alive:
                # Apply capability filter if specified
                if capability is None or capability in worker.capabilities:
                    healthy_workers.append(worker)

        return healthy_workers

    def get_worker_load(self, worker_id: str) -> int:
        """Get current session count for a worker.

        Args:
            worker_id: Worker ID to check

        Returns:
            Number of sessions owned by the worker
        """
        try:
            sessions_key = f"browser:worker_sessions:{worker_id}"
            return int(self.redis.scard(sessions_key))
        except Exception as e:
            logger.error(f"Failed to get worker load for {worker_id}: {e}")
            return 0

    def find_least_loaded_worker(self, capability: str | None = None) -> str | None:
        """Find the worker with lowest load.

        Args:
            capability: Optional capability to filter by

        Returns:
            Worker ID of least loaded worker, or None if no workers available
        """
        healthy_workers = self.get_healthy_workers(capability)

        candidates = healthy_workers
        if not candidates:
            # Fallback to all known workers if no healthy set (e.g., tests without heartbeats)
            candidates = self.get_all_workers()
            if capability is not None:
                candidates = [w for w in candidates if capability in w.capabilities]

        if not candidates:
            return None

        # Sort by load percentage
        candidates.sort(key=lambda w: w.load_percentage)

        # Return the least loaded worker
        return candidates[0].worker_id

    def get_worker_by_id(self, worker_id: str) -> WorkerInfo | None:
        """Get information about a specific worker.

        Args:
            worker_id: Worker ID to look up

        Returns:
            WorkerInfo if found, None otherwise
        """
        try:
            worker_key = f"browser:worker:{worker_id}"
            worker_data = self.redis.hgetall(worker_key)

            if worker_data:
                return self._parse_worker_data(worker_data)

        except Exception as e:
            logger.error(f"Failed to get worker {worker_id}: {e}")

        return None

    def get_orphaned_sessions(self) -> list[str]:
        """Find sessions whose workers are no longer healthy.

        Returns:
            List of orphaned session IDs
        """
        orphaned = []

        try:
            # Get all session affinity keys
            session_keys = self.redis.keys("browser:affinity:*")

            # No capability detection or fallback: standardized heartbeat is authoritative

            for key_str in session_keys:
                session_id = key_str.split(":", 2)[-1]

                worker_id = self.redis.hget(key_str, "worker_id")
                if not worker_id:
                    continue

                # Primary: liveness via standardized heartbeat timestamp
                alive = False
                try:
                    hb_key = f"worker:heartbeat:browser:{worker_id}"
                    ts_raw = self.redis.hget(hb_key, "timestamp")
                    if ts_raw:
                        ts = float(ts_raw)
                        if (time.time() - ts) <= 90.0:
                            alive = True
                except Exception:
                    alive = False

                if not alive:
                    orphaned.append(session_id)

        except Exception as e:
            logger.error(f"Failed to find orphaned sessions: {e}")

        return orphaned

    def cleanup_orphaned_sessions(self) -> int:
        """Remove affinity for sessions whose workers are dead.

        Returns:
            Number of sessions cleaned up
        """
        orphaned = self.get_orphaned_sessions()
        cleaned = 0

        for session_id in orphaned:
            try:
                affinity_key = f"browser:affinity:{session_id}"
                self.redis.delete(affinity_key)
                cleaned += 1
                logger.info(f"Cleaned up orphaned session: {session_id}")
            except Exception as e:
                logger.error(f"Failed to clean up session {session_id}: {e}")

        if cleaned:
            logger.info(f"Cleaned up {cleaned} orphaned sessions")

        return cleaned

    def _parse_worker_data(self, data: dict[str, str]) -> WorkerInfo | None:
        """Parse raw Redis data into WorkerInfo object."""
        try:
            decoded = data

            # Parse specific fields
            capabilities = json.loads(decoded.get("capabilities", "[]"))
            current_sessions = int(decoded.get("current_sessions", "0"))
            max_sessions = int(decoded.get("max_sessions", "10"))

            # Calculate load percentage
            load_percentage = (current_sessions / max_sessions * 100) if max_sessions > 0 else 0.0

            # Parse timestamps
            started_at = datetime.fromisoformat(decoded.get("started_at", ""))
            last_heartbeat = datetime.fromisoformat(decoded.get("last_heartbeat", ""))

            return WorkerInfo(
                worker_id=decoded.get("hostname", "unknown"),
                hostname=decoded.get("hostname", "unknown"),
                capabilities=capabilities,
                status=decoded.get("status", "unknown"),
                current_sessions=current_sessions,
                max_sessions=max_sessions,
                started_at=started_at,
                last_heartbeat=last_heartbeat,
                platform=decoded.get("platform", "unknown"),
                python_version=decoded.get("python_version", "unknown"),
                load_percentage=load_percentage,
            )

        except Exception as e:
            logger.error(f"Failed to parse worker data: {e}")
            return None

    def get_summary(self) -> "WorkerFleetSummary":
        """Get a summary of the worker fleet status.

        Returns:
            Dictionary with fleet statistics
        """
        all_workers = self.get_all_workers()
        healthy_workers = self.get_healthy_workers()

        # Count capabilities
        capability_counts: dict[str, int] = {}
        for worker in healthy_workers:
            for cap in worker.capabilities:
                capability_counts[cap] = capability_counts.get(cap, 0) + 1

        # Calculate total capacity
        total_sessions = sum(w.current_sessions for w in healthy_workers)
        total_capacity = sum(w.max_sessions for w in healthy_workers)

        return {
            "total_workers": len(all_workers),
            "healthy_workers": len(healthy_workers),
            "unhealthy_workers": len(all_workers) - len(healthy_workers),
            "total_sessions": total_sessions,
            "total_capacity": total_capacity,
            "utilization_percentage": (total_sessions / total_capacity * 100)
            if total_capacity > 0
            else 0.0,
            "capabilities": capability_counts,
            "orphaned_sessions": len(self.get_orphaned_sessions()),
        }


class WorkerFleetSummary(TypedDict):
    total_workers: int
    healthy_workers: int
    unhealthy_workers: int
    total_sessions: int
    total_capacity: int
    utilization_percentage: float
    capabilities: dict[str, int]
    orphaned_sessions: int
