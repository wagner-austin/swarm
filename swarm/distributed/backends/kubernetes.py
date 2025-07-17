"""
Kubernetes Scaling Backend
==========================

Implements scaling for Kubernetes deployments.
"""

import asyncio
import json
import logging
import os
from typing import Optional

from swarm.distributed.services.scaling_service import ScalingBackend

logger = logging.getLogger(__name__)


class KubernetesBackend(ScalingBackend):
    """
    Scaling backend for Kubernetes.

    Uses kubectl to scale deployments.
    """

    def __init__(
        self,
        namespace: str = "default",
        deployment_prefix: str = "discord-worker",
        kubeconfig: str | None = None,
    ):
        self.namespace = namespace
        self.deployment_prefix = deployment_prefix
        self.kubeconfig = kubeconfig or os.environ.get("KUBECONFIG")

    async def scale_to(self, worker_type: str, target_count: int) -> bool:
        """Scale worker type to target count."""
        deployment_name = self._get_deployment_name(worker_type)

        try:
            cmd = [
                "kubectl",
                "scale",
                f"deployment/{deployment_name}",
                f"--replicas={target_count}",
                f"--namespace={self.namespace}",
            ]

            if self.kubeconfig:
                cmd.extend(["--kubeconfig", self.kubeconfig])

            logger.info(f"Scaling deployment {deployment_name} to {target_count} replicas")

            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                logger.error(
                    f"Failed to scale {deployment_name}: {stderr.decode() if stderr else 'Unknown error'}"
                )
                return False

            logger.info(f"Successfully scaled {deployment_name} to {target_count}")
            return True

        except Exception as e:
            logger.error(f"Exception scaling {deployment_name}: {e}")
            return False

    async def get_current_count(self, worker_type: str) -> int:
        """Get current number of workers."""
        deployment_name = self._get_deployment_name(worker_type)

        try:
            cmd = [
                "kubectl",
                "get",
                f"deployment/{deployment_name}",
                f"--namespace={self.namespace}",
                "-o",
                "json",
            ]

            if self.kubeconfig:
                cmd.extend(["--kubeconfig", self.kubeconfig])

            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                logger.error(f"Failed to get {deployment_name} status")
                return 0

            # Parse JSON output
            try:
                deployment = json.loads(stdout.decode())
                replicas: int = deployment.get("status", {}).get("readyReplicas", 0)
                return replicas
            except json.JSONDecodeError:
                logger.error("Failed to parse deployment status")
                return 0

        except Exception as e:
            logger.error(f"Exception getting {deployment_name} count: {e}")
            return 0

    def _get_deployment_name(self, worker_type: str) -> str:
        """Map worker type to Kubernetes deployment name."""
        # Example: browser -> discord-worker-browser
        if worker_type == "generic":
            return self.deployment_prefix
        return f"{self.deployment_prefix}-{worker_type}"
