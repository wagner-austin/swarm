"""
Deployment Context Provider
--------------------------
Centralizes deployment context gathering for logging, metrics, and heartbeats.
Injectable for tests and extensibility.
"""

import os
import platform
from typing import Callable, TypedDict


class DeploymentContext(TypedDict):
    hostname: str
    container_id: str
    deployment_env: str
    region: str


def default_deployment_context_provider() -> DeploymentContext:
    # Return a plain dict literal that matches the DeploymentContext shape
    return {
        "hostname": platform.node(),
        "container_id": os.getenv("HOSTNAME", "-"),
        "deployment_env": os.getenv("DEPLOYMENT_ENV", "local"),
        "region": os.getenv("FLY_REGION") or os.getenv("AWS_REGION") or "unknown",
    }


# Type alias for injection
DeploymentContextProvider = Callable[[], DeploymentContext]
