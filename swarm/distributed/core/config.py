"""
Distributed System Configuration
================================

Centralized configuration for the distributed swarm system.
Supports loading from environment variables and provides defaults.
"""

import os
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class ScalingConfig:
    """Configuration for auto-scaling a worker type."""

    min_workers: int
    max_workers: int
    scale_up_threshold: int  # Queue depth to trigger scale up
    scale_down_threshold: int  # Queue depth to trigger scale down
    cooldown_seconds: int = 60  # Time between scaling operations

    @classmethod
    def from_env(cls, prefix: str) -> "ScalingConfig":
        """Load from environment variables with prefix."""
        return cls(
            min_workers=int(os.getenv(f"{prefix}_MIN_WORKERS", "1")),
            max_workers=int(os.getenv(f"{prefix}_MAX_WORKERS", "10")),
            scale_up_threshold=int(os.getenv(f"{prefix}_SCALE_UP_THRESHOLD", "1")),
            scale_down_threshold=int(os.getenv(f"{prefix}_SCALE_DOWN_THRESHOLD", "0")),
            cooldown_seconds=int(os.getenv(f"{prefix}_COOLDOWN", "60")),
        )


@dataclass
class WorkerTypeConfig:
    """Configuration for a specific worker type."""

    name: str
    job_queue: str
    scaling: ScalingConfig
    enabled: bool = True

    @property
    def heartbeat_pattern(self) -> str:
        """Redis pattern for worker heartbeats."""
        return f"worker:heartbeat:{self.name}:*"


class DistributedConfig:
    """
    Central configuration for the distributed system.

    This is the single source of truth for all distributed components.
    """

    def __init__(self) -> None:
        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.metrics_port = int(os.getenv("METRICS_PORT", "9000"))
        self.log_level = os.getenv("LOG_LEVEL", "INFO")

        # Worker type configurations
        self.worker_types: dict[str, WorkerTypeConfig] = {}
        self._load_worker_types()

        # Manager configuration
        self.manager_port = int(os.getenv("MANAGER_PORT", "9150"))
        self.job_timeout = int(os.getenv("JOB_TIMEOUT", "300"))  # 5 minutes

        # Orchestrator configuration
        self.orchestrator_check_interval = int(os.getenv("ORCHESTRATOR_CHECK_INTERVAL", "10"))
        self.worker_health_timeout = int(os.getenv("WORKER_HEALTH_TIMEOUT", "60"))

        # Autoscaler configuration
        self.autoscaler_interval = int(os.getenv("AUTOSCALER_INTERVAL", "30"))
        self.orchestration_backend = os.getenv("ORCHESTRATION_BACKEND", "docker-compose")

    def _load_worker_types(self) -> None:
        """Load worker type configurations."""
        # Default worker types
        self.worker_types["browser"] = WorkerTypeConfig(
            name="browser",
            job_queue="browser:jobs",
            scaling=ScalingConfig(
                min_workers=int(os.getenv("BROWSER_MIN_WORKERS", "1")),
                max_workers=int(os.getenv("BROWSER_MAX_WORKERS", "10")),
                scale_up_threshold=int(os.getenv("BROWSER_SCALE_UP_THRESHOLD", "1")),
                scale_down_threshold=int(os.getenv("BROWSER_SCALE_DOWN_THRESHOLD", "0")),
                cooldown_seconds=int(os.getenv("BROWSER_COOLDOWN", "60")),
            ),
        )

        self.worker_types["tankpit"] = WorkerTypeConfig(
            name="tankpit",
            job_queue="tankpit:jobs",
            scaling=ScalingConfig(
                min_workers=int(os.getenv("TANKPIT_MIN_WORKERS", "0")),
                max_workers=int(os.getenv("TANKPIT_MAX_WORKERS", "50")),
                scale_up_threshold=int(os.getenv("TANKPIT_SCALE_UP_THRESHOLD", "1")),
                scale_down_threshold=int(os.getenv("TANKPIT_SCALE_DOWN_THRESHOLD", "2")),
                cooldown_seconds=int(os.getenv("TANKPIT_COOLDOWN", "60")),
            ),
        )

        # Load custom worker types from environment
        custom_types = os.getenv("CUSTOM_WORKER_TYPES", "").split(",")
        for worker_type in custom_types:
            if worker_type:
                self._load_custom_worker_type(worker_type.strip())

    def _load_custom_worker_type(self, name: str) -> None:
        """Load a custom worker type configuration."""
        prefix = name.upper()
        if os.getenv(f"{prefix}_JOB_QUEUE"):
            self.worker_types[name] = WorkerTypeConfig(
                name=name,
                job_queue=os.getenv(f"{prefix}_JOB_QUEUE", f"{name}:jobs"),
                scaling=ScalingConfig.from_env(prefix),
                enabled=os.getenv(f"{prefix}_ENABLED", "true").lower() == "true",
            )

    def get_worker_type(self, name: str) -> WorkerTypeConfig | None:
        """Get configuration for a worker type."""
        return self.worker_types.get(name)

    def get_enabled_worker_types(self) -> dict[str, WorkerTypeConfig]:
        """Get all enabled worker types."""
        return {name: config for name, config in self.worker_types.items() if config.enabled}

    @classmethod
    def load(cls) -> "DistributedConfig":
        """Load configuration from environment."""
        return cls()


# Global configuration instance
config = DistributedConfig.load()
