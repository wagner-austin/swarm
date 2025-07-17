"""
Tests for Distributed System Configuration
==========================================

Tests configuration loading and management.
"""

import os
from unittest.mock import patch

import pytest

from swarm.distributed.core.config import (
    DistributedConfig,
    ScalingConfig,
    WorkerTypeConfig,
)


class TestScalingConfig:
    """Test the ScalingConfig dataclass."""

    def test_scaling_config_creation(self) -> None:
        """Test creating a scaling configuration."""
        config = ScalingConfig(
            min_workers=2,
            max_workers=10,
            scale_up_threshold=5,
            scale_down_threshold=1,
            cooldown_seconds=30,
        )

        assert config.min_workers == 2
        assert config.max_workers == 10
        assert config.scale_up_threshold == 5
        assert config.scale_down_threshold == 1
        assert config.cooldown_seconds == 30

    def test_scaling_config_from_env(self) -> None:
        """Test loading scaling config from environment."""
        env_vars = {
            "TEST_MIN_WORKERS": "3",
            "TEST_MAX_WORKERS": "15",
            "TEST_SCALE_UP_THRESHOLD": "8",
            "TEST_SCALE_DOWN_THRESHOLD": "2",
            "TEST_COOLDOWN": "45",
        }

        with patch.dict(os.environ, env_vars):
            config = ScalingConfig.from_env("TEST")

        assert config.min_workers == 3
        assert config.max_workers == 15
        assert config.scale_up_threshold == 8
        assert config.scale_down_threshold == 2
        assert config.cooldown_seconds == 45

    def test_scaling_config_from_env_defaults(self) -> None:
        """Test that from_env uses defaults when env vars missing."""
        # No environment variables set
        config = ScalingConfig.from_env("MISSING")

        assert config.min_workers == 1  # default
        assert config.max_workers == 10  # default
        assert config.scale_up_threshold == 1  # default
        assert config.scale_down_threshold == 0  # default
        assert config.cooldown_seconds == 60  # default


class TestWorkerTypeConfig:
    """Test the WorkerTypeConfig dataclass."""

    def test_worker_type_config_creation(self) -> None:
        """Test creating a worker type configuration."""
        scaling = ScalingConfig(
            min_workers=1,
            max_workers=5,
            scale_up_threshold=3,
            scale_down_threshold=0,
        )

        config = WorkerTypeConfig(
            name="test-worker",
            job_queue="test:jobs",
            scaling=scaling,
            enabled=True,
        )

        assert config.name == "test-worker"
        assert config.job_queue == "test:jobs"
        assert config.scaling == scaling
        assert config.enabled is True

    def test_heartbeat_pattern(self) -> None:
        """Test the heartbeat pattern property."""
        config = WorkerTypeConfig(
            name="custom",
            job_queue="custom:jobs",
            scaling=ScalingConfig(1, 5, 3, 0),
        )

        assert config.heartbeat_pattern == "worker:heartbeat:custom:*"


class TestDistributedConfig:
    """Test the DistributedConfig class."""

    def test_default_configuration(self) -> None:
        """Test loading default configuration."""
        config = DistributedConfig()

        # Check defaults
        assert config.redis_url == "redis://localhost:6379/0"
        assert config.metrics_port == 9000
        assert config.log_level == "INFO"
        assert config.manager_port == 9150
        assert config.job_timeout == 300
        assert config.orchestrator_check_interval == 10
        assert config.worker_health_timeout == 60
        assert config.autoscaler_interval == 30
        assert config.orchestration_backend == "docker-compose"

    def test_configuration_from_environment(self) -> None:
        """Test loading configuration from environment variables."""
        env_vars = {
            "REDIS_URL": "redis://custom:6380/1",
            "METRICS_PORT": "8000",
            "LOG_LEVEL": "DEBUG",
            "MANAGER_PORT": "8150",
            "JOB_TIMEOUT": "600",
        }

        with patch.dict(os.environ, env_vars):
            config = DistributedConfig()

        assert config.redis_url == "redis://custom:6380/1"
        assert config.metrics_port == 8000
        assert config.log_level == "DEBUG"
        assert config.manager_port == 8150
        assert config.job_timeout == 600

    def test_default_worker_types(self) -> None:
        """Test that default worker types are loaded."""
        config = DistributedConfig()

        # Should have browser and tankpit by default
        assert "browser" in config.worker_types
        assert "tankpit" in config.worker_types

        # Check browser config
        browser = config.worker_types["browser"]
        assert browser.name == "browser"
        assert browser.job_queue == "browser:jobs"
        assert browser.scaling.min_workers == 1
        assert browser.scaling.max_workers == 10

        # Check tankpit config
        tankpit = config.worker_types["tankpit"]
        assert tankpit.name == "tankpit"
        assert tankpit.job_queue == "tankpit:jobs"
        assert tankpit.scaling.min_workers == 0
        assert tankpit.scaling.max_workers == 50

    def test_custom_worker_type_from_env(self) -> None:
        """Test loading custom worker types from environment."""
        env_vars = {
            "CUSTOM_WORKER_TYPES": "scraper,analyzer",
            "SCRAPER_JOB_QUEUE": "scraper:tasks",
            "SCRAPER_MIN_WORKERS": "2",
            "SCRAPER_MAX_WORKERS": "20",
            "ANALYZER_JOB_QUEUE": "analyzer:tasks",
            "ANALYZER_ENABLED": "false",
        }

        with patch.dict(os.environ, env_vars):
            config = DistributedConfig()

        # Should have custom types
        assert "scraper" in config.worker_types
        assert "analyzer" in config.worker_types

        # Check scraper config
        scraper = config.worker_types["scraper"]
        assert scraper.name == "scraper"
        assert scraper.job_queue == "scraper:tasks"
        assert scraper.scaling.min_workers == 2
        assert scraper.scaling.max_workers == 20
        assert scraper.enabled is True

        # Check analyzer config
        analyzer = config.worker_types["analyzer"]
        assert analyzer.name == "analyzer"
        assert analyzer.job_queue == "analyzer:tasks"
        assert analyzer.enabled is False

    def test_get_worker_type(self) -> None:
        """Test getting a specific worker type configuration."""
        config = DistributedConfig()

        browser = config.get_worker_type("browser")
        assert browser is not None
        assert browser.name == "browser"

        missing = config.get_worker_type("nonexistent")
        assert missing is None

    def test_get_enabled_worker_types(self) -> None:
        """Test getting only enabled worker types."""
        env_vars = {
            "CUSTOM_WORKER_TYPES": "disabled_type",
            "DISABLED_TYPE_JOB_QUEUE": "disabled:jobs",
            "DISABLED_TYPE_ENABLED": "false",
        }

        with patch.dict(os.environ, env_vars):
            config = DistributedConfig()

        enabled = config.get_enabled_worker_types()

        # Should have browser and tankpit (enabled by default)
        assert "browser" in enabled
        assert "tankpit" in enabled

        # Should not have disabled type
        assert "disabled_type" not in enabled

    def test_load_class_method(self) -> None:
        """Test the load() class method."""
        config = DistributedConfig.load()

        assert isinstance(config, DistributedConfig)
        assert "browser" in config.worker_types

    def test_custom_browser_scaling_from_env(self) -> None:
        """Test overriding browser scaling from environment."""
        env_vars = {
            "BROWSER_MIN_WORKERS": "5",
            "BROWSER_MAX_WORKERS": "25",
            "BROWSER_SCALE_UP_THRESHOLD": "10",
        }

        with patch.dict(os.environ, env_vars):
            config = DistributedConfig()

        browser = config.worker_types["browser"]
        assert browser.scaling.min_workers == 5
        assert browser.scaling.max_workers == 25
        assert browser.scaling.scale_up_threshold == 10
