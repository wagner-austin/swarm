"""
Scaling Service
===============

Handles all scaling operations and decisions.
Separates scaling logic from UI/presentation layer.
"""

import asyncio
import logging
import time
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

import redis.asyncio as redis_asyncio

from bot.distributed.core.config import DistributedConfig, WorkerTypeConfig
from bot.distributed.core.pool import WorkerPool

logger = logging.getLogger(__name__)


class ScalingDecision(Enum):
    """Possible scaling decisions."""

    SCALE_UP = "scale_up"
    SCALE_DOWN = "scale_down"
    NO_CHANGE = "no_change"


@runtime_checkable
class ScalingBackend(Protocol):
    """Protocol for scaling backend implementations."""

    async def scale_to(self, worker_type: str, target_count: int) -> bool:
        """Scale worker type to target count."""
        ...

    async def get_current_count(self, worker_type: str) -> int:
        """Get current number of workers."""
        ...


class ScalingService:
    """
    Service responsible for making and executing scaling decisions.

    This service:
    - Monitors queue depths and worker health
    - Makes scaling decisions based on configuration
    - Executes scaling through the configured backend
    - Tracks scaling history and metrics
    """

    def __init__(
        self,
        redis_client: redis_asyncio.Redis,
        config: DistributedConfig,
        backend: ScalingBackend | None = None,
    ):
        self.redis = redis_client
        self.config = config
        self.backend = backend

        # Track last scaling operations
        self.last_scale_time: dict[str, float] = {}
        self.scaling_history: list[dict[str, Any]] = []

        # Worker pools for tracking
        self.pools: dict[str, WorkerPool] = {
            name: WorkerPool(name, config.worker_health_timeout) for name in config.worker_types
        }

    async def get_queue_depth(self, worker_type: str) -> int:
        """Get current queue depth for a worker type."""
        config = self.config.get_worker_type(worker_type)
        if not config:
            return 0

        try:
            depth: int = await self.redis.xlen(config.job_queue)
            return depth
        except Exception as e:
            logger.error(f"Failed to get queue depth for {worker_type}: {e}")
            return 0

    async def update_worker_health(self) -> None:
        """Update worker health from Redis heartbeats."""
        for worker_type, pool in self.pools.items():
            config = self.config.get_worker_type(worker_type)
            if not config:
                continue

            try:
                # Get all worker heartbeats
                pattern = config.heartbeat_pattern
                cursor = 0
                while True:
                    cursor, keys = await self.redis.scan(cursor, match=pattern, count=100)

                    for key in keys:
                        worker_id = key.split(":")[-1]
                        # Redis hget returns bytes or str depending on decode_responses setting
                        heartbeat_data_raw = await self.redis.hget(key, "capabilities")  # type: ignore[misc]
                        heartbeat_data = (
                            heartbeat_data_raw.decode("utf-8")
                            if isinstance(heartbeat_data_raw, bytes)
                            else heartbeat_data_raw
                        )

                        if heartbeat_data:
                            import json

                            capabilities = json.loads(heartbeat_data)
                            pool.register_worker(worker_id, capabilities)
                            pool.mark_healthy(worker_id)

                    if cursor == 0:
                        break

                # Clean up stale workers
                removed = pool.remove_stale_workers()
                if removed:
                    logger.info(f"Removed stale {worker_type} workers: {removed}")

            except Exception as e:
                logger.error(f"Error updating worker health for {worker_type}: {e}")

    def make_scaling_decision(
        self,
        worker_type: str,
        queue_depth: int,
        current_workers: int,
    ) -> tuple[ScalingDecision, int]:
        """
        Make a scaling decision based on current state.

        Returns:
            Tuple of (decision, target_count)
        """
        config = self.config.get_worker_type(worker_type)
        if not config or not config.enabled:
            return ScalingDecision.NO_CHANGE, current_workers

        scaling = config.scaling

        # Check cooldown
        now = time.time()
        last_scale = self.last_scale_time.get(worker_type, 0)
        if now - last_scale < scaling.cooldown_seconds:
            return ScalingDecision.NO_CHANGE, current_workers

        # Make decision
        if queue_depth > scaling.scale_up_threshold and current_workers < scaling.max_workers:
            # Scale up
            target = min(current_workers + 1, scaling.max_workers)
            return ScalingDecision.SCALE_UP, target

        elif queue_depth < scaling.scale_down_threshold and current_workers > scaling.min_workers:
            # Scale down
            target = max(current_workers - 1, scaling.min_workers)
            return ScalingDecision.SCALE_DOWN, target

        return ScalingDecision.NO_CHANGE, current_workers

    async def execute_scaling(
        self,
        worker_type: str,
        decision: ScalingDecision,
        target_count: int,
    ) -> bool:
        """Execute a scaling decision."""
        if decision == ScalingDecision.NO_CHANGE:
            return True

        if not self.backend:
            logger.warning(f"No scaling backend configured, cannot scale {worker_type}")
            return False

        try:
            # Get current count
            current = await self.backend.get_current_count(worker_type)

            # Execute scaling
            logger.info(f"Scaling {worker_type}: {current} -> {target_count} ({decision.value})")
            success = await self.backend.scale_to(worker_type, target_count)

            if success:
                # Update tracking
                self.last_scale_time[worker_type] = time.time()

                # Record history
                self.scaling_history.append(
                    {
                        "timestamp": time.time(),
                        "worker_type": worker_type,
                        "decision": decision.value,
                        "from_count": current,
                        "to_count": target_count,
                        "success": True,
                    }
                )

                # Store event in Redis
                await self._record_scaling_event(worker_type, decision, current, target_count)

            return success

        except Exception as e:
            logger.error(f"Failed to execute scaling for {worker_type}: {e}")
            return False

    async def _record_scaling_event(
        self,
        worker_type: str,
        decision: ScalingDecision,
        from_count: int,
        to_count: int,
    ) -> None:
        """Record scaling event in Redis for monitoring."""
        try:
            await self.redis.xadd(
                "scaling:events",
                {
                    "worker_type": worker_type,
                    "decision": decision.value,
                    "from_count": str(from_count),
                    "to_count": str(to_count),
                    "timestamp": str(time.time()),
                },
                maxlen=1000,
            )
        except Exception as e:
            logger.error(f"Failed to record scaling event: {e}")

    async def check_and_scale_all(self) -> dict[str, bool]:
        """Check all worker types and scale as needed."""
        results = {}

        # Update worker health first
        await self.update_worker_health()

        for worker_type in self.config.get_enabled_worker_types():
            try:
                # Get current state
                queue_depth = await self.get_queue_depth(worker_type)
                pool = self.pools.get(worker_type)
                current_workers = len(pool) if pool else 0

                # Make decision
                decision, target = self.make_scaling_decision(
                    worker_type, queue_depth, current_workers
                )

                # Execute if needed
                if decision != ScalingDecision.NO_CHANGE:
                    success = await self.execute_scaling(worker_type, decision, target)
                    results[worker_type] = success
                else:
                    results[worker_type] = True

            except Exception as e:
                logger.error(f"Error checking/scaling {worker_type}: {e}")
                results[worker_type] = False

        return results

    def get_metrics(self) -> dict[str, Any]:
        """Get scaling service metrics."""
        return {
            "pools": {name: pool.get_statistics() for name, pool in self.pools.items()},
            "last_scale_times": self.last_scale_time.copy(),
            "scaling_history_count": len(self.scaling_history),
            "recent_scaling_events": self.scaling_history[-10:],  # Last 10 events
        }
