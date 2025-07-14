"""
Docker Compose Scaling Backend
==============================

Implements scaling for Docker Compose deployments.
"""

import asyncio
import logging
import os
import subprocess
from typing import Optional

from bot.distributed.services.scaling_service import ScalingBackend

logger = logging.getLogger(__name__)


class DockerComposeBackend(ScalingBackend):
    """
    Scaling backend for Docker Compose.

    Uses docker-compose CLI to scale services up/down.
    """

    def __init__(self, compose_file: str = "docker-compose.yml", project_name: str | None = None):
        self.compose_file = compose_file
        self.project_name = project_name or os.environ.get("COMPOSE_PROJECT_NAME", "discord")

    async def scale_to(self, worker_type: str, target_count: int) -> bool:
        """Scale worker type to target count."""
        service_name = self._get_service_name(worker_type)

        try:
            assert self.project_name is not None, "project_name should not be None"
            cmd: list[str] = [
                "docker-compose",
                "-f",
                self.compose_file,
                "-p",
                self.project_name,
                "up",
                "-d",
                "--scale",
                f"{service_name}={target_count}",
                "--no-recreate",
                service_name,
            ]

            logger.info(f"Scaling {service_name} to {target_count} instances")

            # Run command asynchronously
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                logger.error(
                    f"Failed to scale {service_name}: {stderr.decode() if stderr else 'Unknown error'}"
                )
                return False

            logger.info(f"Successfully scaled {service_name} to {target_count}")
            return True

        except Exception as e:
            logger.error(f"Exception scaling {service_name}: {e}")
            return False

    async def get_current_count(self, worker_type: str) -> int:
        """Get current number of workers."""
        service_name = self._get_service_name(worker_type)

        try:
            assert self.project_name is not None, "project_name should not be None"
            cmd: list[str] = [
                "docker-compose",
                "-f",
                self.compose_file,
                "-p",
                self.project_name,
                "ps",
                "-q",
                service_name,
            ]

            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                logger.error(f"Failed to count {service_name} instances")
                return 0

            # Count non-empty lines (each line is a container ID)
            container_ids = stdout.decode().strip().split("\n")
            count = len([cid for cid in container_ids if cid])

            return count

        except Exception as e:
            logger.error(f"Exception counting {service_name}: {e}")
            return 0

    def _get_service_name(self, worker_type: str) -> str:
        """Map worker type to docker-compose service name."""
        # For now, all worker types use the same service
        # In future, could have worker-browser, worker-tankpit, etc.
        return "worker"
