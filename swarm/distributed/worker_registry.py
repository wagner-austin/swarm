"""Worker registry for querying and managing worker information."""

import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timezone
from typing import TYPE_CHECKING, TypedDict

import redis

from swarm.core.settings import Settings

if TYPE_CHECKING:
    # For type checking, Redis client type
    RedisSyncClient = redis.Redis
else:
    # At runtime, Redis is not generic
    RedisSyncClient = redis.Redis

from swarm.infra.redis_keys import (
    HEARTBEAT_PREFIX,
    WORKER_PREFIX,
    affinity_key as ak,
    heartbeat_key,
    worker_id_from_worker_key,
    worker_key as rk_worker_key,
    worker_sessions_key,
    workers_scan_pattern,
)
from swarm.infra.redis_lua import worker_hashes_for_alive_ids_sync
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


class WorkerStaticFields(TypedDict, total=False):
    hostname: str
    capabilities: list[str]
    max_sessions: int
    platform: str
    python_version: str
    started_at_iso: str


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

        # In-process cache for static worker metadata to reduce repeated decoding/parsing
        self._static_cache: dict[str, WorkerStaticFields] = {}

    def get_all_workers(self) -> list[WorkerInfo]:
        """Get all registered workers (healthy and unhealthy).

        Returns:
            List of WorkerInfo objects
        """
        workers = []

        try:
            # Find all worker keys via SCAN (non-blocking)
            worker_keys = list(self.redis.scan_iter(match=workers_scan_pattern()) or [])

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
        healthy_workers: list[WorkerInfo] = []

        try:
            # Discover worker ids from registry keys via SCAN (non-blocking)
            keys = list(self.redis.scan_iter(match=workers_scan_pattern()) or [])
            worker_ids: list[str] = [worker_id_from_worker_key(k) for k in keys]
            if not worker_ids:
                return []

            # Server-side: filter by heartbeat TTL and return worker hashes
            maps = worker_hashes_for_alive_ids_sync(
                self.redis,
                worker_ids=worker_ids,
                worker_prefix=WORKER_PREFIX,
                heartbeat_prefix=HEARTBEAT_PREFIX,
            )
            for d in maps:
                info = self._parse_worker_data(d)
                if info is None:
                    continue
                if capability is None or capability in info.capabilities:
                    healthy_workers.append(info)
        except Exception as e:
            logger.error(f"Failed to get healthy workers: {e}")
            return []

        return healthy_workers

    def get_worker_load(self, worker_id: str) -> int:
        """Get current session count for a worker.

        Args:
            worker_id: Worker ID to check

        Returns:
            Number of sessions owned by the worker
        """
        try:
            sessions_key = worker_sessions_key(worker_id)
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
            # No fallbacks: require heartbeat-backed liveness
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
            worker_key = rk_worker_key(worker_id)
            worker_data = self.redis.hgetall(worker_key)

            if worker_data:
                return self._parse_worker_data(worker_data)

        except Exception as e:
            logger.error(f"Failed to get worker {worker_id}: {e}")

        return None

    def get_orphaned_sessions(self) -> list[str]:
        """Return sessions whose owning worker is no longer live (authoritative).

        Delegates to the SessionRegistry's canonical logic to avoid drift.
        """
        try:
            from swarm.distributed.session_registry import SessionRegistry

            return SessionRegistry.find_orphaned_sessions_sync(self.redis)
        except Exception as e:
            logger.error(f"Failed to compute orphaned sessions: {e}")
            return []

    def cleanup_orphaned_sessions(self) -> int:
        """Remove affinity for sessions whose workers are dead.

        Returns:
            Number of sessions cleaned up
        """
        orphaned = self.get_orphaned_sessions()
        cleaned = 0

        for session_id in orphaned:
            try:
                self.redis.delete(ak(session_id))
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
            worker_id = decoded.get("hostname", "unknown")

            # Static fields with cache
            static = self._static_cache.get(worker_id)
            started_at_iso = decoded.get("started_at", "")
            if (
                static is None
                or static.get("started_at_iso") != started_at_iso
                or "capabilities" not in static
            ):
                # Refresh cache when worker restarts or cache miss
                caps = json.loads(decoded.get("capabilities", "[]"))
                static = {
                    "hostname": decoded.get("hostname", "unknown"),
                    "capabilities": caps if isinstance(caps, list) else [],
                    "max_sessions": int(decoded.get("max_sessions", "10")),
                    "platform": decoded.get("platform", "unknown"),
                    "python_version": decoded.get("python_version", "unknown"),
                    "started_at_iso": started_at_iso,
                }
                self._static_cache[worker_id] = static

            capabilities = static.get("capabilities", [])
            max_sessions = int(static.get("max_sessions", 10))
            current_sessions = int(decoded.get("current_sessions", "0"))

            # Calculate load percentage
            load_percentage = (current_sessions / max_sessions * 100) if max_sessions > 0 else 0.0

            # Parse timestamps
            started_at = (
                datetime.fromisoformat(started_at_iso)
                if started_at_iso
                else datetime.fromtimestamp(0, tz=UTC)
            )
            last_heartbeat_iso = decoded.get("last_heartbeat", "")
            last_heartbeat = (
                datetime.fromisoformat(last_heartbeat_iso)
                if last_heartbeat_iso
                else datetime.fromtimestamp(0, tz=UTC)
            )

            return WorkerInfo(
                worker_id=worker_id,
                hostname=static.get("hostname", worker_id),
                capabilities=capabilities,
                status=decoded.get("status", "unknown"),
                current_sessions=current_sessions,
                max_sessions=max_sessions,
                started_at=started_at,
                last_heartbeat=last_heartbeat,
                platform=static.get("platform", "unknown"),
                python_version=static.get("python_version", "unknown"),
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
