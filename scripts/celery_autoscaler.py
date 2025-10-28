#!/usr/bin/env python3
"""
Celery-aware Autoscaler (Flower-free)
====================================

This autoscaler monitors Celery queues without Flower, using:
- Celery Control/Inspect for topology when needed
- Direct Redis queue depth checks via the configured broker URL

It scales container counts via a pluggable backend (docker-api, k8s, fly).
"""

import argparse
import asyncio
import logging
import os
import random
import signal
import sys
from typing import Callable, Protocol, TypedDict, TypeGuard

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kombu.connection import Connection
from prometheus_client import Gauge, start_http_server

from swarm.core.logger_setup import bootstrap_logging
from swarm.distributed.backends import DockerApiBackend, FlyIOBackend, KubernetesBackend
from swarm.distributed.core.config import DistributedConfig, WorkerTypeConfig
from swarm.distributed.protocols import ScalingBackend, ScalingDecision

__all__ = ["CeleryAutoscaler"]

# Logger instance (configured in main via bootstrap)
logger = logging.getLogger(__name__)

# Prometheus metrics
AS_QUEUE_DEPTH = Gauge(
    "autoscaler_queue_depth",
    "Aggregated queue depth (base + direct.*) used by autoscaler",
    ["queue"],
)
AS_DECISION = Gauge(
    "autoscaler_decision",
    "Autoscaler decision code (1=up, 0=none, -1=down)",
    ["worker_type"],
)
AS_TARGET = Gauge(
    "autoscaler_target",
    "Autoscaler target worker count",
    ["worker_type"],
)


class CeleryAutoscaler:
    """
    Autoscaler that monitors Celery queues without Flower.

    Maintains container-level scaling while Celery handles
    process-level scaling within each container.
    """

    def __init__(
        self,
        orchestrator: str = "docker-api",
        check_interval: int = 30,
    ):
        self.orchestrator = orchestrator
        self.check_interval = check_interval
        self.backend: ScalingBackend | None = None
        self.config: DistributedConfig | None = None
        self._shutdown_event = asyncio.Event()
        self._conn: Connection | None = None
        self.priority_steps: tuple[int, ...] = (0,)

    async def setup(self) -> None:
        """Set up the autoscaler."""
        # Ensure logging has contextual fields when used programmatically (e.g. tests)
        try:
            bootstrap_logging(service="celery-autoscaler")
        except Exception:
            # Logging may already be configured; proceed regardless
            pass

        logger.info("Celery Autoscaler starting up")
        logger.info(f"Orchestrator: {self.orchestrator}")
        logger.info(f"Check interval: {self.check_interval}s")
        logger.info(f"Environment: {os.getenv('DEPLOYMENT_ENV', 'local')}")

        # Load configuration
        self.config = DistributedConfig.load()
        logger.info(
            f"Loaded config with {len(self.config.worker_types)} worker types: {list(self.config.worker_types.keys())}"
        )

        # Eagerly initialize broker connection via Celery (fail fast on misconfig)
        try:
            from swarm.celery_app import app as celery_app

            conn: Connection = celery_app.connection()
            conn.ensure_connection(max_retries=3)
            self._conn = conn
            # Capture priority steps for Redis transport accounting
            opts = celery_app.conf.get("broker_transport_options", {})
            steps_cfg = opts.get("priority_steps", [0])
            # Normalize to a validated tuple[int, ...]
            steps: list[int] = []
            for val in steps_cfg:
                try:
                    steps.append(int(val))
                except Exception:
                    continue
            self.priority_steps = tuple(steps) if steps else (0,)
            logger.info("Autoscaler connected to Celery broker")
        except Exception as e:
            logger.error(f"Failed to connect to Celery broker: {e}", exc_info=True)
            raise SystemExit(2)

        # Select backend
        if self.orchestrator == "docker" or self.orchestrator == "docker-api":
            project_name = os.environ.get("COMPOSE_PROJECT_NAME", "swarm")
            worker_metrics_port = int(os.environ.get("WORKER_METRICS_PORT", "9100"))
            self.backend = DockerApiBackend(
                image="swarm-worker:latest",
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

        logger.info(f"Using {self.orchestrator} backend for scaling")

        # Install signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._make_signal_handler(sig))
            except NotImplementedError:
                pass

    def _make_signal_handler(self, sig: signal.Signals) -> "Callable[[], None]":
        """Return a zero-arg callback that schedules async shutdown for `sig`."""

        def _handler() -> None:
            # Schedule the async shutdown task and return immediately
            asyncio.create_task(self._on_signal(sig))

        return _handler

        # Optional Prometheus metrics endpoint for autoscaler
        port_str = os.getenv("AUTOSCALER_METRICS_PORT")
        if port_str:
            try:
                port = int(port_str)
                start_http_server(port, addr="0.0.0.0")
                logger.info(f"Autoscaler metrics server started on :{port}")
            except Exception as e:
                logger.warning(f"Failed to start autoscaler metrics endpoint: {e}")

    async def _on_signal(self, sig: signal.Signals) -> None:
        """Handle shutdown signals."""
        logger.info(f"Received signal {sig.name} - shutting down")
        self._shutdown_event.set()

    class QueueStatEntry(TypedDict):
        depth: int

    class _RedisClient(Protocol):
        def llen(self, name: str) -> int: ...

    class _RedisChannel(Protocol):
        client: "CeleryAutoscaler._RedisClient"

        def _q_for_pri(self, name: str, pri: int) -> str: ...

    @staticmethod
    def _is_redis_channel(obj: object) -> TypeGuard["CeleryAutoscaler._RedisChannel"]:
        return hasattr(obj, "client") and hasattr(obj, "_q_for_pri")

    async def get_queue_stats(self) -> dict[str, "CeleryAutoscaler.QueueStatEntry"]:
        """Get queue depths using Kombu SimpleQueue.qsize() per queue."""
        if not self.config:
            return {}

        if self._conn is None:
            logger.error("Broker connection not initialized")
            return {}

        stats: dict[str, CeleryAutoscaler.QueueStatEntry] = {}

        # For each enabled worker type, aggregate base + direct queues
        for _, cfg in self.config.worker_types.items():
            if not getattr(cfg, "enabled", False):
                continue
            base = str(getattr(cfg, "job_queue", "")).split(":")[0]
            if not base:
                continue

            queue_names = self.discover_queues(base)
            if not queue_names:
                queue_names = {base}

            total_depth = 0
            for name in sorted(queue_names):
                try:
                    depth = await asyncio.to_thread(self.queue_depth, name)
                    total_depth += int(depth)
                except Exception as e:
                    logger.warning(f"Failed to read depth for queue {name}: {e}")
                    continue

            stats[base] = {"depth": int(total_depth)}
            # Update metrics for this base queue
            try:
                AS_QUEUE_DEPTH.labels(queue=base).set(int(total_depth))
            except Exception:
                pass

        return stats

    def discover_queues(self, base_prefix: str) -> set[str]:
        """Return a set of queue names to consider for scaling.

        Includes the base queue and any per-worker direct queues matching
        "<base_prefix>.direct.*" discovered via Celery Inspect.
        """
        try:
            from swarm.celery_app import app as celery_app

            inspector = celery_app.control.inspect()
            active_queues = inspector.active_queues() or {}
            names: set[str] = set()
            direct_prefix = base_prefix + ".direct."
            for queues in active_queues.values():
                if not queues:
                    continue
                for q in queues:
                    name = q.get("name")
                    if not name:
                        continue
                    if name == base_prefix or name.startswith(direct_prefix):
                        names.add(name)
            return names
        except Exception as e:
            logger.debug(f"discover_queues failed: {e}")
            return set()

    def queue_depth(self, name: str) -> int:
        """Return current ready depth for a queue name on Redis broker.

        This implementation requires the Kombu Redis transport and computes
        depth by summing per-priority Redis list lengths for the queue.
        """
        if self._conn is None:
            raise RuntimeError("Broker connection not initialized")

        ch = self._conn.default_channel
        if not CeleryAutoscaler._is_redis_channel(ch):
            raise RuntimeError("Redis broker/transport is required for autoscaler queue depth")

        total = 0
        for pri in self.priority_steps:
            key = ch._q_for_pri(name, pri)
            total += int(ch.client.llen(key))

        return int(total)

    async def get_worker_stats(self) -> dict[str, int]:
        """Get worker statistics via Celery Inspect (optional)."""
        try:
            from swarm.celery_app import app as celery_app

            inspector = celery_app.control.inspect()
            active_queues = inspector.active_queues() or {}
            workers_per_queue: dict[str, int] = {}
            for _, queues in active_queues.items():
                for q in queues or []:
                    name = q.get("name")
                    if name:
                        workers_per_queue[name] = workers_per_queue.get(name, 0) + 1
            return workers_per_queue
        except Exception as e:
            logger.warning(f"Celery Inspect failed: {e}")
            return {}

    def make_scaling_decision(
        self,
        queue_name: str,
        queue_depth: int,
        current_workers: int,
        config: WorkerTypeConfig,
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

        # Get queue depths from broker (and optionally worker stats via Inspect)
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
            queue_info: CeleryAutoscaler.QueueStatEntry = queue_stats.get(queue_name, {"depth": 0})
            queue_depth = int(queue_info.get("depth", 0))

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

            # Update autoscaler decision/target metrics
            try:
                code = (
                    1
                    if decision == ScalingDecision.SCALE_UP
                    else (-1 if decision == ScalingDecision.SCALE_DOWN else 0)
                )
                AS_DECISION.labels(worker_type=worker_type).set(code)
                AS_TARGET.labels(worker_type=worker_type).set(target)
            except Exception:
                pass

    async def run(self) -> None:
        """Run the autoscaler loop."""
        logger.info(f"Starting Celery autoscaler with {self.check_interval}s interval")

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
        logger.info("Starting cleanup process...")
        try:
            if self._conn is not None:
                self._conn.close()
        except Exception:
            pass

        # Clean up worker containers if using Docker
        if self.backend and hasattr(self.backend, "cleanup_all_workers"):
            logger.info("Cleaning up worker containers...")
            try:
                await self.backend.cleanup_all_workers()
                logger.info("Worker cleanup completed successfully")
            except Exception as e:
                logger.error(f"Error cleaning up workers: {e}")
        else:
            logger.warning(
                f"Backend {type(self.backend).__name__} does not support cleanup_all_workers"
            )


async def main() -> None:
    """Run the autoscaler main loop."""
    parser = argparse.ArgumentParser(description="Celery-aware Worker Autoscaler (Flower-free)")
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
    # No Flower authentication/options

    args = parser.parse_args()

    # Configure logging and bind deployment/service context
    bootstrap_logging(service="celery-autoscaler")

    autoscaler = CeleryAutoscaler(
        orchestrator=args.orchestrator,
        check_interval=args.check_interval,
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
