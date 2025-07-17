#!/usr/bin/env python3
"""
Production Worker Autoscaler
============================

This script monitors Redis job queues and scales workers up/down based on demand.
It uses the ScalingService from the distributed system to handle scaling operations.

Usage:
    python -m scripts.autoscaler --orchestrator docker-compose
"""

import argparse
import asyncio
import logging
import os
import signal
import sys
from typing import Callable

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import redis.asyncio as redis_asyncio

from swarm.core.settings import Settings
from swarm.distributed.backends import DockerApiBackend, FlyIOBackend, KubernetesBackend
from swarm.distributed.core.config import DistributedConfig
from swarm.distributed.services.scaling_service import ScalingBackend, ScalingService
from swarm.infra.redis_factory import create_redis_client
from swarm.types import RedisBytes

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class WorkerAutoscaler:
    """
    Production autoscaler that uses the ScalingService.

    This is a thin wrapper that initializes the appropriate backend
    and runs the scaling service continuously.
    """

    def __init__(
        self,
        redis_url: str,
        orchestrator: str = "docker-compose",
        check_interval: int = 30,
    ):
        self.redis_url = redis_url
        self.orchestrator = orchestrator
        self.check_interval = check_interval
        self.scaling_service: ScalingService | None = None
        self.redis: RedisBytes | None = None
        # Shutdown coordination
        self._shutdown_event: asyncio.Event = asyncio.Event()
        self._signal_handlers_installed = False

    async def setup(self) -> None:
        """Set up the autoscaler with appropriate backend."""
        # Connect to Redis with automatic fallback
        self.redis = await create_redis_client()
        logger.info("Connected to Redis with automatic fallback support")

        # Load distributed configuration
        config = DistributedConfig.load()

        # Select backend based on orchestrator
        backend: ScalingBackend
        if self.orchestrator == "docker" or self.orchestrator == "docker-api":
            # Use docker API backend for proper container management
            # Docker compose builds images with specific names
            project_name = os.environ.get("COMPOSE_PROJECT_NAME", "swarm")
            worker_metrics_port = int(os.environ.get("WORKER_METRICS_PORT", "9100"))
            backend = DockerApiBackend(
                image="swarm:latest",  # The actual built image name
                network=None,  # Auto-detect the network
                project_name=project_name,
                app_mount_path=None,  # Auto-detect the app path
                worker_metrics_port=worker_metrics_port,
            )
        elif self.orchestrator == "kubernetes":
            namespace = os.environ.get("K8S_NAMESPACE", "default")
            backend = KubernetesBackend(namespace=namespace)
        elif self.orchestrator == "fly":
            backend = FlyIOBackend()
        else:
            raise ValueError(f"Unknown orchestrator: {self.orchestrator}")

        logger.info(f"Using {self.orchestrator} backend for scaling")

        # Install signal handlers for graceful shutdown (once per process)
        if not self._signal_handlers_installed:
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                try:
                    loop.add_signal_handler(sig, self._make_signal_handler(sig))
                except NotImplementedError:
                    # Signal handling not supported (e.g., Windows); skip
                    pass
            self._signal_handlers_installed = True

        # Create scaling service
        self.scaling_service = ScalingService(
            redis_client=self.redis, config=config, backend=backend
        )

    def _make_signal_handler(self, sig: signal.Signals) -> Callable[[], None]:
        """Return a sync callback that schedules async _on_signal."""

        def _handler() -> None:  # pragma: no cover
            asyncio.create_task(self._on_signal(sig))

        return _handler

    async def _on_signal(self, sig: signal.Signals) -> None:
        """Handle OS signals for graceful shutdown."""
        logger.info("Received signal %s – shutting down", sig.name)
        self._shutdown_event.set()

    async def run(self) -> None:
        """Run the autoscaler continuously."""
        if not self.scaling_service:
            raise RuntimeError("Autoscaler not set up. Call setup() first.")

        logger.info(f"Starting autoscaler with {self.check_interval}s check interval")

        try:
            while not self._shutdown_event.is_set():
                try:
                    # Run scaling check
                    await self.scaling_service.check_and_scale_all()
                except Exception as e:
                    logger.error(f"Error during scaling check: {e}")

                # Wait before next check
                await asyncio.sleep(self.check_interval)

        except asyncio.CancelledError:
            logger.info("Autoscaler task cancelled – shutting down...")
            self._shutdown_event.set()
        finally:
            # Ensure cleanup even if loop exits normally
            await self.cleanup()

    async def cleanup(self) -> None:
        """Clean up resources."""
        # Clean up all worker containers if using Docker backend
        if self.scaling_service and isinstance(self.scaling_service.backend, DockerApiBackend):
            logger.info("Cleaning up all worker containers...")
            try:
                await self.scaling_service.backend.cleanup_all_workers()
                logger.info("Worker cleanup complete")
            except Exception as e:
                logger.error(f"Error cleaning up workers: {e}")

        if self.redis:
            close_coro = getattr(self.redis, "aclose", None)
            if callable(close_coro):
                await close_coro()
            else:
                # Fall back to sync close() for test fakes
                close_fn = getattr(self.redis, "close", None)
                if callable(close_fn):
                    close_fn()

        # Remove custom signal handlers to avoid leakage in tests / reloads
        if self._signal_handlers_installed:
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                try:
                    loop.remove_signal_handler(sig)
                except Exception:
                    pass
            self._signal_handlers_installed = False


async def main() -> None:
    """Run the autoscaler main loop."""
    parser = argparse.ArgumentParser(description="Worker Autoscaler")
    parser.add_argument(
        "--redis-url",
        type=str,
        default=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
        help="Redis URL",
    )
    parser.add_argument(
        "--orchestrator",
        type=str,
        choices=["docker", "docker-api", "kubernetes", "fly"],
        default=os.environ.get("ORCHESTRATOR", "docker"),
        help="Container orchestrator (docker/docker-api uses Docker API)",
    )
    parser.add_argument(
        "--check-interval",
        type=int,
        default=int(os.environ.get("CHECK_INTERVAL", "30")),
        help="Seconds between scaling checks",
    )

    args = parser.parse_args()

    # Create and run autoscaler
    autoscaler = WorkerAutoscaler(
        redis_url=args.redis_url, orchestrator=args.orchestrator, check_interval=args.check_interval
    )

    try:
        await autoscaler.setup()
        await autoscaler.run()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    finally:
        await autoscaler.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
