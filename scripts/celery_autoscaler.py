#!/usr/bin/env python3
"""
Celery-aware Autoscaler using Flower API
========================================

This autoscaler monitors Celery queues via Flower's REST API and manages
worker containers. It replaces the Redis streams-based autoscaler.

Key differences from the old autoscaler:
1. Uses Flower API for queue metrics (more accurate than Redis XLEN)
2. Monitors actual Celery queue depths, not Redis streams
3. Can see reserved vs waiting tasks
4. Works with Celery's built-in autoscaling

Usage:
    python -m scripts.celery_autoscaler --flower-url http://localhost:5555
"""

import argparse
import asyncio
import logging
import os
import random
import signal
import sys
from contextlib import nullcontext
from typing import Any, Dict

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import aiohttp
import async_timeout

from swarm.distributed.backends import DockerApiBackend, FlyIOBackend, KubernetesBackend
from swarm.distributed.core.config import DistributedConfig
from swarm.distributed.services.scaling_service import ScalingBackend, ScalingDecision

__all__ = ["CeleryAutoscaler"]

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class CeleryAutoscaler:
    """
    Autoscaler that monitors Celery queues via Flower API.

    This maintains the container-level scaling while Celery handles
    process-level scaling within each container.
    """

    def __init__(
        self,
        flower_url: str = "http://localhost:5555",
        orchestrator: str = "docker-api",
        check_interval: int = 30,
        flower_username: str | None = None,
        flower_password: str | None = None,
    ):
        self.flower_url = flower_url.rstrip("/")
        self.orchestrator = orchestrator
        self.check_interval = check_interval
        self.flower_username = flower_username
        self.flower_password = flower_password
        self.backend: ScalingBackend | None = None
        self.config: DistributedConfig | None = None
        self._shutdown_event = asyncio.Event()
        self._session: aiohttp.ClientSession | None = None
        self._auth: aiohttp.BasicAuth | None = None

    async def setup(self) -> None:
        """Set up the autoscaler."""
        # Load configuration
        self.config = DistributedConfig.load()

        # Create HTTP session for Flower API
        self._session = aiohttp.ClientSession()

        # Set up auth if provided
        if self.flower_username and self.flower_password:
            self._auth = aiohttp.BasicAuth(self.flower_username, self.flower_password)

        # Select backend
        if self.orchestrator == "docker" or self.orchestrator == "docker-api":
            project_name = os.environ.get("COMPOSE_PROJECT_NAME", "swarm")
            worker_metrics_port = int(os.environ.get("WORKER_METRICS_PORT", "9100"))
            self.backend = DockerApiBackend(
                image="swarm:latest",
                network=None,
                project_name=project_name,
                app_mount_path=None,
                worker_metrics_port=worker_metrics_port,
            )
        elif self.orchestrator == "kubernetes":
            namespace = os.environ.get("K8S_NAMESPACE", "default")
            self.backend = KubernetesBackend(namespace=namespace)
        elif self.orchestrator == "fly":
            self.backend = FlyIOBackend()
        else:
            raise ValueError(f"Unknown orchestrator: {self.orchestrator}")

        logger.info(f"Using {self.orchestrator} backend with Flower at {self.flower_url}")

        # Install signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(
                    sig,
                    lambda s=sig: asyncio.create_task(self._on_signal(s)),  # type: ignore[misc]
                )
            except NotImplementedError:
                pass

    async def _on_signal(self, sig: signal.Signals) -> None:
        """Handle shutdown signals."""
        logger.info(f"Received signal {sig.name} - shutting down")
        self._shutdown_event.set()

    async def get_queue_stats(self) -> dict[str, dict[str, int]]:
        """Get queue statistics from Flower API."""
        if not self._session:
            return {}

        try:
            # Get queue length from Flower with timeout
            async with async_timeout.timeout(10):
                # Support both real aiohttp response and mock responses
                resp = await self._session.get(
                    f"{self.flower_url}/api/queues/length", auth=self._auth
                )
                async with resp if hasattr(resp, "__aenter__") else nullcontext(resp):
                    if hasattr(resp, "status") and resp.status != 200:
                        logger.error(f"Flower API returned status {resp.status}")
                        return {}

                    data = await resp.json()
                    queue_stats: dict[str, dict[str, int]] = {}

                    # Process active queues
                    active_queues = data.get("active_queues", [])
                    for queue in active_queues:
                        name = queue.get("name", "")
                        if name:
                            ready = queue.get("messages_ready", 0)
                            unacked = queue.get("messages_unacknowledged", 0)
                            queue_stats[name] = {
                                "depth": ready + unacked,  # Total queue depth
                                "messages_ready": ready,
                                "messages_unacknowledged": unacked,
                            }

                    return queue_stats

        except TimeoutError:
            logger.error("Timeout getting queue stats from Flower")
            return {}
        except Exception as e:
            logger.error(f"Failed to get queue stats from Flower: {e}")
            return {}

    async def get_worker_stats(self) -> dict[str, int]:
        """Get worker statistics from Flower API."""
        if not self._session:
            return {}

        try:
            # Get worker stats with timeout
            async with async_timeout.timeout(10):
                # Support both real aiohttp response and mock responses
                resp = await self._session.get(f"{self.flower_url}/api/workers", auth=self._auth)
                async with resp if hasattr(resp, "__aenter__") else nullcontext(resp):
                    if hasattr(resp, "status") and resp.status != 200:
                        return {}

                    data = await resp.json()

                    # Count workers per queue
                    workers_per_queue: dict[str, int] = {}
                    for worker_name, worker_info in data.items():
                        # Get active queues for this worker
                        active_queues = worker_info.get("active_queues", [])
                        for queue in active_queues:
                            queue_name = queue.get("name", "")
                            if queue_name:
                                workers_per_queue[queue_name] = (
                                    workers_per_queue.get(queue_name, 0) + 1
                                )

                    return workers_per_queue

        except TimeoutError:
            logger.error("Timeout getting worker stats from Flower")
            return {}
        except Exception as e:
            logger.error(f"Failed to get worker stats from Flower: {e}")
            return {}

    def make_scaling_decision(
        self,
        queue_name: str,
        queue_depth: int,
        current_workers: int,
        config: Any,
    ) -> tuple[ScalingDecision, int]:
        """Make scaling decision for a queue."""
        scaling = config.scaling

        # Ensure minimum workers
        if current_workers < scaling.min_workers:
            return ScalingDecision.SCALE_UP, scaling.min_workers

        # Scale up if queue is building up
        if queue_depth >= scaling.scale_up_threshold and current_workers < scaling.max_workers:
            return ScalingDecision.SCALE_UP, min(current_workers + 1, scaling.max_workers)

        # Scale down if queue is empty (with cooldown)
        if queue_depth <= scaling.scale_down_threshold and current_workers > scaling.min_workers:
            target = max(current_workers - 1, scaling.min_workers)
            # Only return scale down if we're actually changing
            if target != current_workers:
                return ScalingDecision.SCALE_DOWN, target

        return ScalingDecision.NO_CHANGE, current_workers

    async def check_and_scale(self) -> None:
        """Check all queues and scale as needed."""
        if not self.config or not self.backend:
            return

        # Get queue and worker stats from Flower
        queue_stats = await self.get_queue_stats()
        # Note: worker_stats not currently used, but kept for future queue routing
        # worker_stats = await self.get_worker_stats()

        # Check each worker type
        for worker_type, config in self.config.worker_types.items():
            if not config.enabled:
                continue

            # Get queue name (e.g., "browser" from "browser:jobs")
            queue_name = config.job_queue.split(":")[0]

            # Get queue depth (use pre-calculated depth)
            queue_info = queue_stats.get(queue_name, {})
            queue_depth = queue_info.get("depth", 0)

            # Get current workers from backend (container count)
            current_workers = await self.backend.get_current_count(worker_type)

            # Make scaling decision
            decision, target = self.make_scaling_decision(
                queue_name, queue_depth, current_workers, config
            )

            # Execute if needed (double-check target != current)
            if decision != ScalingDecision.NO_CHANGE and target != current_workers:
                logger.info(
                    f"Scaling {worker_type}: {current_workers} -> {target} "
                    f"(queue depth: {queue_depth})"
                )
                await self.backend.scale_to(worker_type, target)

    async def run(self) -> None:
        """Run the autoscaler loop."""
        logger.info(f"Starting Celery autoscaler with {self.check_interval}s interval")

        # Wait for Flower to be ready
        await asyncio.sleep(5)

        while not self._shutdown_event.is_set():
            try:
                await self.check_and_scale()
            except Exception as e:
                logger.error(f"Error during scaling check: {e}")

            # Wait for next check with jitter to avoid thundering herd
            jitter = random.uniform(0, self.check_interval * 0.1)  # 10% jitter
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(), timeout=self.check_interval + jitter
                )
            except TimeoutError:
                pass

    async def cleanup(self) -> None:
        """Clean up resources."""
        if self._session:
            await self._session.close()

        # Clean up worker containers if using Docker
        if self.backend and hasattr(self.backend, "cleanup_all_workers"):
            logger.info("Cleaning up worker containers...")
            try:
                await self.backend.cleanup_all_workers()
            except Exception as e:
                logger.error(f"Error cleaning up workers: {e}")


async def main() -> None:
    """Run the autoscaler main loop."""
    parser = argparse.ArgumentParser(description="Celery-aware Worker Autoscaler")
    parser.add_argument(
        "--flower-url",
        type=str,
        default=os.environ.get("FLOWER_URL", "http://localhost:5555"),
        help="Flower API URL",
    )
    parser.add_argument(
        "--orchestrator",
        type=str,
        choices=["docker", "docker-api", "kubernetes", "fly"],
        default=os.environ.get("ORCHESTRATOR", "docker-api"),
        help="Container orchestrator",
    )
    parser.add_argument(
        "--check-interval",
        type=int,
        default=int(os.environ.get("CHECK_INTERVAL", "30")),
        help="Seconds between checks",
    )
    parser.add_argument(
        "--username",
        type=str,
        default=os.environ.get("FLOWER_USERNAME"),
        help="Flower basic auth username",
    )
    parser.add_argument(
        "--password",
        type=str,
        default=os.environ.get("FLOWER_PASSWORD"),
        help="Flower basic auth password",
    )

    args = parser.parse_args()

    autoscaler = CeleryAutoscaler(
        flower_url=args.flower_url,
        orchestrator=args.orchestrator,
        check_interval=args.check_interval,
        flower_username=args.username,
        flower_password=args.password,
    )

    try:
        await autoscaler.setup()
        await autoscaler.run()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    finally:
        await autoscaler.cleanup()


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(main())
