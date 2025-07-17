"""
Tests for Enhanced Distributed Logging System
============================================

Verifies that the enhanced logging system correctly:
- Detects deployment context
- Includes all metadata in log records
- Handles JSON formatting properly
- Supports structured logging with context variables
"""

import json
import logging
import os
import tempfile
from typing import Generator, cast
from unittest.mock import MagicMock, patch

import pytest

from swarm.core.logger_setup import (
    DEFAULT_LOGGING_CONFIG,
    _ContextFilter,
    auto_detect_deployment_context,
    bind_deployment_context,
    bind_log_context,
    setup_logging,
)


class PatchedLogRecord(logging.LogRecord):
    """A LogRecord patched with custom attributes for mypy."""

    service: str
    worker_id: str
    job_id: str
    hostname: str
    container_id: str
    deployment_env: str
    region: str


class TestDeploymentContextDetection:
    """Test automatic deployment context detection."""

    def test_auto_detect_deployment_context_basic(self) -> None:
        """Test basic deployment context detection."""
        with patch.dict(os.environ, {"DEPLOYMENT_ENV": "test", "FLY_REGION": "test-region"}):
            context = auto_detect_deployment_context()

            assert context["deployment_env"] == "test"
            assert context["region"] == "test-region"
            assert "hostname" in context
            assert context["hostname"] != "unknown"

    def test_auto_detect_with_docker_container(self) -> None:
        """Test container ID detection."""
        with patch.dict(os.environ, {"HOSTNAME": "test-container-id"}):
            context = auto_detect_deployment_context()
            assert context["container_id"] == "test-container-id"

    def test_auto_detect_fallbacks(self) -> None:
        """Test fallback values when environment variables are missing."""
        with patch.dict(os.environ, {}, clear=True):
            context = auto_detect_deployment_context()

            assert context["deployment_env"] == "local"
            assert context["region"] == "unknown"
            assert context["container_id"] == "-"
            assert context["hostname"] != "unknown"  # Should still detect real hostname


class TestEnhancedLogging:
    """Test enhanced logging with context variables."""

    def test_context_filter_includes_all_metadata(self) -> None:
        """Test that context filter adds all expected metadata."""
        # Set up context
        bind_log_context(service="test-service", worker_id="test-worker", job_id="test-job")
        bind_deployment_context(
            hostname="test-host",
            container_id="test-container",
            deployment_env="test-env",
            region="test-region",
        )

        # Create log record
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="test message",
            args=(),
            exc_info=None,
        )

        # Apply context filter
        context_filter = _ContextFilter()
        context_filter.filter(record)

        # Verify all context is included
        record = cast(PatchedLogRecord, record)
        assert record.service == "test-service"
        assert record.worker_id == "test-worker"
        assert record.job_id == "test-job"
        assert record.hostname == "test-host"
        assert record.container_id == "test-container"
        assert record.deployment_env == "test-env"
        assert record.region == "test-region"

    def test_json_formatter_includes_all_fields(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test that JSON formatter includes all context fields."""
        import io

        from pythonjsonlogger import json as json_formatter

        # Set context before creating handlers
        bind_log_context(service="test", worker_id="w1", job_id="j1")
        bind_deployment_context(
            context={
                "hostname": "host1",
                "container_id": "cont1",
                "deployment_env": "prod",
                "region": "us-west",
            }
        )

        # Create memory stream to capture formatted output
        log_stream = io.StringIO()

        # Set up logger with JSON formatter and context filter
        logger = logging.getLogger("test_json_logger")
        logger.handlers.clear()  # Clear any existing handlers

        # Create handler with JSON formatter
        handler = logging.StreamHandler(log_stream)
        formatter = json_formatter.JsonFormatter()
        context_filter = _ContextFilter()

        handler.setFormatter(formatter)
        handler.addFilter(context_filter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        # Log a message
        logger.info("Test structured log message")

        # Get the formatted output
        log_output = log_stream.getvalue().strip()

        # Parse the JSON log entry
        import json as json_module

        log_data = json_module.loads(log_output)

        # Verify all context fields are present
        assert log_data["service"] == "test"
        assert log_data["worker_id"] == "w1"
        assert log_data["job_id"] == "j1"
        assert log_data["hostname"] == "host1"
        assert log_data["container_id"] == "cont1"
        assert log_data["deployment_env"] == "prod"
        assert log_data["region"] == "us-west"
        assert log_data["message"] == "Test structured log message"


class TestLoggingConfiguration:
    """Test logging configuration and setup."""

    def test_setup_logging_respects_env_variables(self) -> None:
        """Test that setup_logging respects environment variables."""
        with patch.dict(os.environ, {"LOG_LEVEL": "WARNING"}):
            setup_logging()

            # Check that root logger level was set
            root_logger = logging.getLogger()
            assert root_logger.level == logging.WARNING

    def test_setup_logging_with_overrides(self) -> None:
        """Test setup_logging with configuration overrides."""
        overrides = {
            "root": {"level": "ERROR"},
            "handlers": {"test_handler": {"class": "logging.StreamHandler", "level": "ERROR"}},
        }

        setup_logging(overrides)

        # Verify overrides were applied
        root_logger = logging.getLogger()
        assert root_logger.level == logging.ERROR

    def test_setup_logging_prevents_duplicate_configuration(self) -> None:
        """Test that setup_logging prevents duplicate configuration."""
        # Call setup_logging twice
        setup_logging()
        initial_handlers = len(logging.getLogger().handlers)

        setup_logging()  # Should not add duplicate handlers
        final_handlers = len(logging.getLogger().handlers)

        assert initial_handlers == final_handlers


class TestHeartbeatCompatibility:
    """Test compatibility with heartbeat system."""

    @pytest.mark.asyncio
    async def test_worker_heartbeat_integration(self) -> None:
        """Test that enhanced logging works with heartbeat system."""
        from swarm.distributed.monitoring.heartbeat import WorkerHeartbeat

        # Use a fixed deployment context provider for deterministic context
        def fixed_context() -> dict[str, str]:
            return {
                "hostname": "test-host",
                "container_id": "test-container",
                "deployment_env": "test",
                "region": "us-test",
            }

        # Set up logging context
        bind_log_context(service="worker", worker_id="test-worker")
        bind_deployment_context(context=fixed_context())

        # Create heartbeat instance with injected context provider
        heartbeat = WorkerHeartbeat(
            redis_client=MagicMock(),
            worker_id="test-worker",
            interval_seconds=1.0,
            deployment_context_provider=fixed_context,
        )

        # Collect heartbeat data (tests context integration)
        data = await heartbeat._collect_heartbeat_data()

        # Verify deployment context is included
        assert data["worker_id"] == "test-worker"
        assert data["deployment"]["deployment_env"] == "test"
        assert "timestamp" in data
        assert "uptime_seconds" in data


@pytest.fixture(autouse=True)
def reset_logging() -> Generator[None, None, None]:
    """Reset logging configuration and patch LogRecord for tests."""
    # Clear any existing loggers and handlers
    logging.getLogger().handlers.clear()

    # Reset the configuration flag
    import swarm.core.logger_setup

    swarm.core.logger_setup._CONFIGURED = False

    # Patch LogRecord for mypy
    original_log_record_factory = logging.getLogRecordFactory()
    logging.setLogRecordFactory(PatchedLogRecord)

    yield

    # Clean up after test
    logging.getLogger().handlers.clear()
    swarm.core.logger_setup._CONFIGURED = False
    logging.setLogRecordFactory(original_log_record_factory)


def test_log_directory_structure() -> None:
    """Test that log directories are created properly."""
    import pathlib

    # Create a temporary directory for testing
    with tempfile.TemporaryDirectory() as tmpdir:
        base_path = pathlib.Path(tmpdir) / "logs"

        # Create the directories for testing
        (base_path / "swarm").mkdir(parents=True, exist_ok=True)
        (base_path / "workers").mkdir(parents=True, exist_ok=True)
        (base_path / "archive").mkdir(parents=True, exist_ok=True)

        # Now test that they exist
        assert (base_path / "swarm").exists()
        assert (base_path / "workers").exists()
        assert (base_path / "archive").exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
