"""
Heartbeat and Status Reporting System for Distributed Workers
============================================================

This module provides a heartbeat mechanism for workers to periodically report
their status, resource usage, and health to a central Redis broker. This enables
real-time monitoring and observability of the distributed worker fleet.

Usage:
    heartbeat = WorkerHeartbeat(redis_client, worker_id="worker-1")
    await heartbeat.start()  # Starts background heartbeat task
    await heartbeat.stop()   # Graceful shutdown
"""

import asyncio
import json
import logging
import platform
import time
from typing import TYPE_CHECKING, Any, Awaitable, Dict, Optional, cast

import psutil
import redis.asyncio as redis_asyncio

from swarm.core.deployment_context import (
    DeploymentContextProvider,
    default_deployment_context_provider,
)
from swarm.types import RedisBytes

if TYPE_CHECKING:
    from ..worker import Worker

logger = logging.getLogger(__name__)


class WorkerHeartbeat:
    """
    Manages periodic heartbeat reporting for distributed workers.

    Reports worker status, resource usage, and job statistics to Redis
    for centralized monitoring and observability.
    """

    def __init__(
        self,
        redis_client: RedisBytes,
        worker_id: str,
        interval_seconds: float = 30.0,
        worker: Optional["Worker"] = None,
        deployment_context_provider: DeploymentContextProvider = default_deployment_context_provider,
    ) -> None:
        self.redis_client = redis_client
        self.worker_id = worker_id
        self.interval_seconds = interval_seconds
        self.worker = worker
        self.deployment_context_provider = deployment_context_provider
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._start_time = time.time()

        # Redis keys
        self.heartbeat_key = f"worker:heartbeat:{worker_id}"
        self.status_stream = "worker:status"

    async def start(self) -> None:
        """Start the background heartbeat task."""
        if self._task is not None:
            logger.warning("Heartbeat already started")
            return

        logger.info(
            f"Starting heartbeat for worker {self.worker_id} (interval: {self.interval_seconds}s)"
        )
        self._task = asyncio.create_task(self._heartbeat_loop())

    async def stop(self) -> None:
        """Stop the heartbeat task gracefully."""
        if self._task is None:
            return

        logger.info(f"Stopping heartbeat for worker {self.worker_id}")
        self._stop_event.set()

        try:
            await asyncio.wait_for(self._task, timeout=5.0)
        except TimeoutError:
            logger.warning("Heartbeat task did not stop gracefully, cancelling")
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        self._task = None

    async def _heartbeat_loop(self) -> None:
        """Run the main heartbeat loop in the background."""
        while not self._stop_event.is_set():
            try:
                await self._send_heartbeat()
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.interval_seconds)
            except TimeoutError:
                # Expected - continue the loop
                continue
            except Exception as e:
                logger.error(f"Error in heartbeat loop: {e}", exc_info=True)
                # Continue despite errors to maintain heartbeat
                await asyncio.sleep(5.0)

        logger.info(f"Heartbeat loop stopped for worker {self.worker_id}")

    async def _send_heartbeat(self) -> None:
        """Collect and send heartbeat data to Redis."""
        try:
            heartbeat_data = await self._collect_heartbeat_data()

            # Determine worker type from job_type_prefix
            worker_type = "unknown"
            if self.worker and hasattr(self.worker, "job_type_prefix"):
                worker_type = self.worker.job_type_prefix or "general"

            # Update heartbeat key to include worker type for orchestrator
            typed_heartbeat_key = f"worker:heartbeat:{worker_type}:{self.worker_id}"

            # Store latest status in Redis hash (for quick lookups)
            await cast(
                Awaitable[int],
                self.redis_client.hset(
                    typed_heartbeat_key,
                    mapping={
                        k: json.dumps(v) if isinstance(v, dict | list) else str(v)
                        for k, v in heartbeat_data.items()
                    },
                ),
            )

            # Set TTL so dead workers are automatically cleaned up
            await cast(
                Awaitable[int],
                self.redis_client.expire(typed_heartbeat_key, int(self.interval_seconds * 3)),
            )

            # Also add to status stream for time-series analysis
            stream_data: dict[str | bytes, str | bytes] = {
                k: json.dumps(v) if isinstance(v, dict | list) else str(v)
                for k, v in heartbeat_data.items()
            }
            await self.redis_client.xadd(
                self.status_stream,
                stream_data,
                maxlen=10000,  # Keep last 10k status updates
            )

            logger.debug(f"Heartbeat sent for worker {self.worker_id}")

        except Exception as e:
            logger.error(f"Failed to send heartbeat: {e}", exc_info=True)

    async def _collect_heartbeat_data(self) -> dict[str, Any]:
        """Collect comprehensive worker status and resource data."""
        data = {
            "worker_id": self.worker_id,
            "timestamp": time.time(),
            "uptime_seconds": time.time() - self._start_time,
        }

        # Worker state (if available)
        if self.worker:
            data.update(
                {
                    "state": self.worker.get_state().name,
                    "state_value": self.worker.get_state().value,
                    "backoff_seconds": self.worker._backoff,
                    "job_type_prefix": self.worker.job_type_prefix,
                }
            )

            # Job statistics (if worker tracks them)
            if hasattr(self.worker, "jobs_processed"):
                data["jobs_processed"] = getattr(self.worker, "jobs_processed", 0)
            if hasattr(self.worker, "jobs_failed"):
                data["jobs_failed"] = getattr(self.worker, "jobs_failed", 0)

        # System information
        try:
            process = psutil.Process()
            memory_info = process.memory_info()

            data.update(
                {
                    "system": {
                        "hostname": platform.node(),
                        "platform": platform.platform(),
                        "python_version": platform.python_version(),
                        "pid": process.pid,
                    },
                    "resources": {
                        "memory_mb": round(memory_info.rss / 1024 / 1024, 2),
                        "memory_percent": round(process.memory_percent(), 2),
                        "cpu_percent": round(process.cpu_percent(), 2),
                        "num_threads": process.num_threads(),
                        "open_files": len(process.open_files()),
                    },
                }
            )

            # System-wide resource info
            data["system_resources"] = {
                "cpu_count": psutil.cpu_count(),
                "memory_total_gb": round(psutil.virtual_memory().total / 1024 / 1024 / 1024, 2),
                "memory_available_gb": round(
                    psutil.virtual_memory().available / 1024 / 1024 / 1024, 2
                ),
                "disk_usage_percent": round(psutil.disk_usage("/").percent, 2),
            }

        except Exception as e:
            data["system_error"] = str(e)
            logger.warning(f"Could not collect system metrics: {e}")

        # Deployment context (injectable)
        data["deployment"] = self.deployment_context_provider()

        return data


async def get_all_worker_heartbeats(
    redis_client: RedisBytes,
) -> dict[str, dict[str, Any]]:
    """
    Retrieve heartbeat data for all active workers.

    Returns:
        Dictionary mapping worker_id to their latest heartbeat data.
    """
    pattern = "worker:heartbeat:*"
    workers = {}

    try:
        keys = await cast(Awaitable[list[bytes]], redis_client.keys(pattern))
        for key in keys:
            worker_id = key.decode().split(":")[-1]
            raw_data = await cast(
                Awaitable[dict[bytes, bytes]], redis_client.hgetall(key.decode("utf-8"))
            )

            # Parse JSON fields back to objects
            worker_data = {}
            for field, value in raw_data.items():
                field_str = field.decode() if isinstance(field, bytes) else field
                value_str = value.decode() if isinstance(value, bytes) else value

                try:
                    # Try to parse as JSON first
                    worker_data[field_str] = json.loads(value_str)
                except (json.JSONDecodeError, TypeError):
                    # Fall back to string value
                    worker_data[field_str] = value_str

            workers[worker_id] = worker_data

    except Exception as e:
        logger.error(f"Failed to retrieve worker heartbeats: {e}")

    return workers


async def cleanup_stale_heartbeats(redis_client: RedisBytes, max_age_seconds: int = 300) -> int:
    """
    Clean up heartbeat data for workers that haven't reported in max_age_seconds.

    Returns:
        Number of stale worker heartbeats cleaned up.
    """
    pattern = "worker:heartbeat:*"
    cleaned_count = 0
    current_time = time.time()

    try:
        keys = await cast(Awaitable[list[bytes]], redis_client.keys(pattern))
        for key in keys:
            last_timestamp = await cast(
                Awaitable[bytes | None], redis_client.hget(key.decode("utf-8"), "timestamp")
            )
            if last_timestamp:
                try:
                    timestamp = float(last_timestamp.decode())
                    if current_time - timestamp > max_age_seconds:
                        await redis_client.delete(key.decode() if isinstance(key, bytes) else key)
                        cleaned_count += 1
                        logger.info(f"Cleaned up stale heartbeat: {key.decode()}")
                except (ValueError, AttributeError):
                    # Invalid timestamp, clean it up
                    await redis_client.delete(key.decode() if isinstance(key, bytes) else key)
                    cleaned_count += 1

    except Exception as e:
        logger.error(f"Failed to cleanup stale heartbeats: {e}")

    return cleaned_count
