"""
Fly.io Scaling Backend
======================

Implements scaling for Fly.io deployments.
"""

import asyncio
import json
import logging
import os
from typing import Optional

from bot.distributed.services.scaling_service import ScalingBackend

logger = logging.getLogger(__name__)


class FlyIOBackend(ScalingBackend):
    """
    Scaling backend for Fly.io.

    Uses fly CLI to scale machines.
    """

    def __init__(
        self, app_name: str | None = None, process_group: str = "worker", region: str | None = None
    ):
        self.app_name = app_name or os.environ.get("FLY_APP_NAME")
        self.process_group = process_group
        self.region = region or os.environ.get("FLY_REGION", "primary")

        if not self.app_name:
            raise ValueError("Fly.io app name must be provided or set in FLY_APP_NAME env var")

    async def scale_to(self, worker_type: str, target_count: int) -> bool:
        """Scale worker type to target count."""
        process_name = self._get_process_name(worker_type)

        try:
            assert self.app_name is not None, "app_name should not be None"
            cmd: list[str] = [
                "fly",
                "scale",
                "count",
                f"{process_name}={target_count}",
                "--app",
                self.app_name,
            ]

            if self.region and self.region != "primary":
                cmd.extend(["--region", self.region])

            logger.info(f"Scaling {process_name} to {target_count} machines")

            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                logger.error(
                    f"Failed to scale {process_name}: {stderr.decode() if stderr else 'Unknown error'}"
                )
                return False

            logger.info(f"Successfully scaled {process_name} to {target_count}")
            return True

        except Exception as e:
            logger.error(f"Exception scaling {process_name}: {e}")
            return False

    async def get_current_count(self, worker_type: str) -> int:
        """Get current number of workers."""
        process_name = self._get_process_name(worker_type)

        try:
            assert self.app_name is not None, "app_name should not be None"
            cmd: list[str] = ["fly", "status", "--app", self.app_name, "--json"]

            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                logger.error("Failed to get app status")
                return 0

            # Parse JSON output and count machines in the process group
            try:
                status = json.loads(stdout.decode())
                machines = status.get("Machines", [])

                # Count machines that match our process group and are running
                count = sum(
                    1
                    for m in machines
                    if m.get("process_group") == process_name
                    and m.get("state") in ["started", "running"]
                )

                return count

            except json.JSONDecodeError:
                logger.error("Failed to parse Fly.io status")
                return 0

        except Exception as e:
            logger.error(f"Exception getting {process_name} count: {e}")
            return 0

    def _get_process_name(self, worker_type: str) -> str:
        """Map worker type to Fly.io process group name."""
        # Example: browser -> worker-browser
        if worker_type == "generic":
            return self.process_group
        return f"{self.process_group}-{worker_type}"
