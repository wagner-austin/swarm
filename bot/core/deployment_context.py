"""
Deployment Context Provider
--------------------------
Centralizes deployment context gathering for logging, metrics, and heartbeats.
Injectable for tests and extensibility.
"""

import os
import platform
from typing import Callable, Dict


def default_deployment_context_provider() -> dict[str, str]:
    return {
        "hostname": platform.node(),
        "container_id": os.getenv("HOSTNAME", "-"),
        "deployment_env": os.getenv("DEPLOYMENT_ENV", "local"),
        "region": os.getenv("FLY_REGION") or os.getenv("AWS_REGION") or "unknown",
    }


# Type alias for injection
DeploymentContextProvider = Callable[[], dict[str, str]]
