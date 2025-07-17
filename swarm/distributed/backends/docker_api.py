"""
Docker API Scaling Backend
==========================

Implements scaling using direct Docker API for proper container lifecycle management.
"""

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

try:
    import docker
    from docker.errors import DockerException, NotFound
    from docker.models.containers import Container
except ImportError:
    raise ImportError("Docker SDK required. Install with: pip install docker")

from swarm.distributed.services.scaling_service import ScalingBackend

logger = logging.getLogger(__name__)


class DockerApiBackend(ScalingBackend):
    """
    Scaling backend using Docker API directly.

    This provides better control over container lifecycle compared to docker-compose scaling.
    """

    def __init__(
        self,
        image: str = "swarm:latest",
        network: str | None = None,
        project_name: str = "swarm",
        app_mount_path: str | None = None,
        worker_metrics_port: int = 9100,
    ):
        """
        Initialize Docker API backend.

        Args:
            image: Docker image to use for workers
            network: Docker network name (usually projectname_default)
            project_name: Project name prefix for containers
            app_mount_path: Path to mount as /app in container (auto-detected if None)
            worker_metrics_port: Port for worker metrics endpoint (default: 9100)
        """
        self.image = image
        self.project_name = project_name
        self.client = docker.from_env()
        self.worker_metrics_port = worker_metrics_port

        # Auto-detect app mount path if not provided
        if app_mount_path is None:
            self.app_mount_path = self._detect_app_path()
        else:
            self.app_mount_path = app_mount_path

        # Auto-detect network if not provided
        if network is None:
            self.network = self._detect_compose_network()
        else:
            self.network = network

    async def scale_to(self, worker_type: str, target_count: int) -> bool:
        """Scale worker type to target count."""
        try:
            current_count = await self.get_current_count(worker_type)

            if current_count == target_count:
                logger.info(f"{worker_type} already at {target_count} instances")
                return True

            if current_count < target_count:
                # Scale up
                containers_to_create = target_count - current_count
                logger.info(f"Scaling up {worker_type}: creating {containers_to_create} containers")

                for i in range(containers_to_create):
                    success = await self._create_worker_container(
                        worker_type, current_count + i + 1
                    )
                    if not success:
                        logger.error(f"Failed to create worker {current_count + i + 1}")
                        return False

            else:
                # Scale down
                containers_to_remove = current_count - target_count
                logger.info(
                    f"Scaling down {worker_type}: removing {containers_to_remove} containers"
                )

                containers = await self._get_worker_containers(worker_type)
                # Remove the highest numbered containers first
                containers.sort(key=lambda c: self._get_container_number(c.name), reverse=True)

                for container in containers[:containers_to_remove]:
                    await self._remove_container(container)

            return True

        except Exception as e:
            logger.error(f"Failed to scale {worker_type} to {target_count}: {e}")
            return False

    async def get_current_count(self, worker_type: str) -> int:
        """Get current number of workers."""
        try:
            containers = await self._get_worker_containers(worker_type)
            return len(containers)
        except Exception as e:
            logger.error(f"Failed to count {worker_type} containers: {e}")
            return 0

    async def _create_worker_container(self, worker_type: str, instance_num: int) -> bool:
        """Create a single worker container."""
        container_name = f"{self.project_name}_{worker_type}_{instance_num}"

        # Proactively remove any pre-existing container with the same name to avoid
        # 409 Conflict errors if a crashed container was left behind.
        try:
            existing_container = self.client.containers.get(container_name)
            logger.warning(
                "Container '%s' already exists with status '%s'. Removing it before recreation.",
                container_name,
                existing_container.status,
            )
            await self._remove_container(existing_container)
        except NotFound:
            # Expected case – there is no container with that name.
            pass
        except Exception as cleanup_exc:
            logger.error(
                "Error removing pre-existing container %s: %s", container_name, cleanup_exc
            )
            return False

        try:
            # Environment variables for Celery worker
            environment = {
                "CELERY_BROKER_URL": "redis://redis:6379/0",
                "CELERY_RESULT_BACKEND": "redis://redis:6379/0",
                "DISPLAY": ":99",
                "LOG_FORMAT": "json",
                "LOG_TO_FILE": "0",
                "PYTHONPATH": "/app",
                "WORKER_TYPE": worker_type,  # For worker identification
                "CELERY_QUEUES": worker_type,  # Which queue to consume
                "CELERY_HOSTNAME": f"{worker_type}-{instance_num}@%h",
                "CELERY_CONCURRENCY": "2",
                "CELERY_LOGLEVEL": "info",
            }

            # Container configuration
            config: dict[str, Any] = {
                "image": self.image,
                "name": container_name,
                "entrypoint": ["/usr/local/bin/entrypoint.worker.sh"],
                "environment": environment,
                "working_dir": "/app",
                "network": self.network,
                "detach": True,
                "restart_policy": {"Name": "unless-stopped"},
                "labels": {
                    "com.docker.compose.project": self.project_name,
                    "com.docker.compose.service": worker_type,
                    "discord.worker.type": worker_type,
                    "discord.worker.number": str(instance_num),
                },
                "volumes": {
                    # Mount the app directory
                    self.app_mount_path: {
                        "bind": "/app",
                        "mode": "rw",
                    }
                },
                # Add health check for workers
                "healthcheck": {
                    "test": [
                        "CMD",
                        "curl",
                        "-f",
                        f"http://localhost:{self.worker_metrics_port}/metrics",
                    ],
                    "interval": 30000000000,  # 30s in nanoseconds
                    "timeout": 5000000000,  # 5s in nanoseconds
                    "retries": 3,
                    "start_period": 60000000000,  # 60s in nanoseconds
                },
            }

            # Run in executor to avoid blocking
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: self.client.containers.run(**config))

            logger.info(f"Created worker container: {container_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to create container {container_name}: {e}")
            return False

    async def _remove_container(self, container: Container) -> None:
        """Remove a container."""
        try:
            container_name = container.name

            # Run in executor to avoid blocking
            loop = asyncio.get_event_loop()

            # Stop the container
            await loop.run_in_executor(None, container.stop)

            # Remove the container
            await loop.run_in_executor(None, container.remove)

            logger.info(f"Removed container: {container_name}")

        except NotFound:
            logger.debug(f"Container already removed: {container.name}")
        except Exception as e:
            logger.error(f"Failed to remove container {container.name}: {e}")

    async def _get_worker_containers(self, worker_type: str) -> list[Container]:
        """Get all containers for a worker type."""
        try:
            # Run in executor to avoid blocking
            loop = asyncio.get_event_loop()

            filters = {
                "label": [
                    f"com.docker.compose.project={self.project_name}",
                    f"discord.worker.type={worker_type}",
                ],
                "status": "running",
            }

            containers = await loop.run_in_executor(
                None, lambda: self.client.containers.list(filters=filters)
            )

            return list(containers)

        except Exception as e:
            logger.error(f"Failed to list {worker_type} containers: {e}")
            return []

    def _get_container_number(self, container_name: str) -> int:
        """Extract instance number from container name."""
        try:
            # Format: projectname_worker_N
            parts = container_name.split("_")
            return int(parts[-1])
        except (ValueError, IndexError):
            return 0

    async def cleanup_all_workers(self) -> None:
        """
        Clean up all worker containers.

        This is useful for ensuring no orphaned containers remain after docker compose down.
        """
        try:
            # Get all worker containers (including stopped ones)
            loop = asyncio.get_event_loop()

            filters = {
                "label": f"com.docker.compose.project={self.project_name}",
            }

            # Get both running and stopped containers
            all_containers = await loop.run_in_executor(
                None, lambda: self.client.containers.list(all=True, filters=filters)
            )

            # Filter for only worker containers (those with discord.worker.type label)
            worker_containers = [c for c in all_containers if "discord.worker.type" in c.labels]

            logger.info(f"Found {len(worker_containers)} worker containers to clean up")

            for container in worker_containers:
                await self._remove_container(container)

        except Exception as e:
            logger.error(f"Failed to cleanup worker containers: {e}")

    def _detect_compose_network(self) -> str:
        """Auto-detect the Docker Compose network."""
        try:
            # List all networks and find one that matches compose pattern
            networks = self.client.networks.list()

            # Look for networks with _default suffix
            for net in networks:
                if net.name.endswith("_default") and net.name != "bridge_default":
                    network_name: str = str(net.name)
                    logger.info("Auto-detected Docker Compose network: %s", network_name)
                    return network_name

            # Fallback to common patterns
            logger.warning("Could not auto-detect network, using discord_default")
            return "discord_default"

        except Exception as e:
            logger.error(f"Failed to detect network: {e}, using discord_default")
            return "discord_default"

    def _detect_app_path(self) -> str:
        """Auto-detect the application directory path by inspecting our own container."""
        import socket

        # If we're running inside a container, inspect our own mounts
        hostname = socket.gethostname()
        try:
            # Try to get our own container info
            container = self.client.containers.get(hostname)

            # Look for the /app mount
            for mount in container.attrs.get("Mounts", []):
                if mount.get("Destination") == "/app":
                    source_any = mount.get("Source")
                    source: str = str(source_any)
                    logger.info("Found /app mount from container inspection: %s", source)
                    return source

        except Exception as e:
            logger.debug(f"Could not inspect container mounts: {e}")

        # If we can't inspect container, we must be running on the host
        # Use the current working directory
        cwd = os.getcwd()
        logger.info(f"Using current working directory: {cwd}")
        return cwd
