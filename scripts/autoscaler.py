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
import sys

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import redis.asyncio as redis_asyncio

from bot.distributed.backends import DockerComposeBackend, FlyIOBackend, KubernetesBackend
from bot.distributed.core.config import DistributedConfig
from bot.distributed.services.scaling_service import ScalingBackend, ScalingService

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
        self.redis: redis_asyncio.Redis | None = None

    async def setup(self) -> None:
        """Set up the autoscaler with appropriate backend."""
        # Connect to Redis
        self.redis = redis_asyncio.from_url(self.redis_url)  # type: ignore[no-untyped-call]
        logger.info(f"Connected to Redis at {self.redis_url}")

        # Load distributed configuration
        config = DistributedConfig.load()

        # Select backend based on orchestrator
        backend: ScalingBackend
        if self.orchestrator == "docker-compose":
            backend = DockerComposeBackend()
        elif self.orchestrator == "kubernetes":
            namespace = os.environ.get("K8S_NAMESPACE", "default")
            backend = KubernetesBackend(namespace=namespace)
        elif self.orchestrator == "fly":
            backend = FlyIOBackend()
        else:
            raise ValueError(f"Unknown orchestrator: {self.orchestrator}")

        logger.info(f"Using {self.orchestrator} backend for scaling")

        # Create scaling service
        self.scaling_service = ScalingService(
            redis_client=self.redis, config=config, backend=backend
        )

    async def run(self) -> None:
        """Run the autoscaler continuously."""
        if not self.scaling_service:
            raise RuntimeError("Autoscaler not set up. Call setup() first.")

        logger.info(f"Starting autoscaler with {self.check_interval}s check interval")

        try:
            while True:
                try:
                    # Run scaling check
                    await self.scaling_service.check_and_scale_all()
                except Exception as e:
                    logger.error(f"Error during scaling check: {e}")

                # Wait before next check
                await asyncio.sleep(self.check_interval)

        except asyncio.CancelledError:
            logger.info("Autoscaler shutting down...")
            raise

    async def cleanup(self) -> None:
        """Clean up resources."""
        if self.redis:
            await self.redis.close()


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
        choices=["docker-compose", "kubernetes", "fly"],
        default=os.environ.get("ORCHESTRATOR", "docker-compose"),
        help="Container orchestrator",
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
        logger.info("Received interrupt signal")
    finally:
        await autoscaler.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
