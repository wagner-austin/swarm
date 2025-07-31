"""
Scaling Backend Implementations
===============================

Concrete implementations of the ScalingBackend protocol for different orchestrators.
"""

from swarm.distributed.backends.docker_api import DockerApiBackend
from swarm.distributed.backends.fly_io import FlyIOBackend
from swarm.distributed.backends.kubernetes import KubernetesBackend
from swarm.distributed.protocols import ScalingBackend, ScalingDecision

__all__ = [
    "ScalingBackend",
    "ScalingDecision",
    "DockerApiBackend",
    "FlyIOBackend",
    "KubernetesBackend",
]
