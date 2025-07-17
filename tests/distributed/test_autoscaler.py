"""
Tests for the Production Autoscaler Service
===========================================

Tests the autoscaler script that runs in production.
"""

import asyncio
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.distributed.backends import DockerApiBackend
from bot.distributed.core.config import DistributedConfig
from scripts.autoscaler import WorkerAutoscaler
from tests.fakes.fake_redis import FakeRedisClient
from tests.fakes.fake_scaling_backend import FakeScalingBackend


class TestWorkerAutoscaler:
    """Test the production autoscaler service."""

    @pytest.fixture
    def fake_redis_client(self) -> FakeRedisClient:
        """Create a fake Redis client."""
        return FakeRedisClient()

    @pytest.fixture
    def config(self) -> DistributedConfig:
        """Create test configuration."""
        return DistributedConfig()

    @pytest.mark.asyncio
    async def test_autoscaler_setup(self, fake_redis_client: FakeRedisClient) -> None:
        """Test autoscaler initialization and setup."""
        autoscaler = WorkerAutoscaler(
            redis_url="redis://fake",
            orchestrator="docker",
            check_interval=1,
        )

        # Mock redis connection
        with patch("redis.asyncio.from_url") as mock_from_url:
            mock_from_url.return_value = fake_redis_client

            await autoscaler.setup()

            # Verify setup completed
            assert autoscaler.redis is not None
            assert autoscaler.scaling_service is not None
            assert isinstance(autoscaler.scaling_service.backend, DockerApiBackend)

    @pytest.mark.asyncio
    async def test_autoscaler_continuous_monitoring(
        self, fake_redis_client: FakeRedisClient
    ) -> None:
        """Test that autoscaler continuously monitors and scales."""
        # Create autoscaler with short interval
        autoscaler = WorkerAutoscaler(
            redis_url="redis://fake",
            orchestrator="docker",
            check_interval=1,  # 1 second for testing
        )

        # Set up with fake backend
        fake_backend = FakeScalingBackend(initial_counts={"browser": 0})

        with patch("redis.asyncio.from_url") as mock_from_url:
            mock_from_url.return_value = fake_redis_client

            await autoscaler.setup()

            # Replace backend with fake
            assert autoscaler.scaling_service is not None
            autoscaler.scaling_service.backend = fake_backend

            # Add jobs to trigger scaling - use the correct queue for browser workers
            await fake_redis_client.xadd("browser:jobs", {"job": "test1"})
            await fake_redis_client.xadd("browser:jobs", {"job": "test2"})

            # Run autoscaler for a short time
            run_task = asyncio.create_task(autoscaler.run())

            # Wait for at least one check cycle (check_interval is 1 second)
            await asyncio.sleep(1.5)

            # Cancel the run task
            run_task.cancel()
            try:
                await run_task
            except asyncio.CancelledError:
                pass

            # Verify scaling occurred
            assert fake_backend.was_scaled("browser")
            assert await fake_backend.get_current_count("browser") > 0

    @pytest.mark.asyncio
    async def test_autoscaler_error_handling(self, fake_redis_client: FakeRedisClient) -> None:
        """Test that autoscaler handles errors gracefully."""
        autoscaler = WorkerAutoscaler(
            redis_url="redis://fake",
            orchestrator="docker",
            check_interval=1,  # Use 1 second interval for testing
        )

        with patch("redis.asyncio.from_url") as mock_from_url:
            mock_from_url.return_value = fake_redis_client

            await autoscaler.setup()

            # Replace backend with fake to avoid real cleanup
            fake_backend = FakeScalingBackend()
            assert autoscaler.scaling_service is not None
            autoscaler.scaling_service.backend = fake_backend

            # Track calls
            call_count = 0

            async def error_after_calls() -> None:
                nonlocal call_count
                call_count += 1
                if call_count >= 2:
                    # Set shutdown after a couple calls
                    autoscaler._shutdown_event.set()
                raise Exception("Test error")

            # Make scaling service raise an error
            autoscaler.scaling_service.check_and_scale_all = AsyncMock(  # type: ignore[method-assign]
                side_effect=error_after_calls
            )

            # Run autoscaler - it should exit after a few error cycles
            await autoscaler.run()

            # Should have called check_and_scale_all at least once despite errors
            assert call_count >= 2

    @pytest.mark.asyncio
    async def test_autoscaler_cleanup(self, fake_redis_client: FakeRedisClient) -> None:
        """Test that autoscaler cleans up resources."""
        autoscaler = WorkerAutoscaler(
            redis_url="redis://fake",
            orchestrator="docker",
        )

        with patch("redis.asyncio.from_url") as mock_from_url:
            mock_redis = AsyncMock()
            mock_from_url.return_value = mock_redis

            await autoscaler.setup()

            # Replace backend with fake to avoid real Docker operations
            fake_backend = FakeScalingBackend()
            if autoscaler.scaling_service:
                autoscaler.scaling_service.backend = fake_backend

            await autoscaler.cleanup()

            # Verify Redis connection was closed
            mock_redis.aclose.assert_called_once()

    @pytest.mark.parametrize(
        "orchestrator,expected_backend",
        [
            ("docker", "DockerApiBackend"),
            ("kubernetes", "KubernetesBackend"),
            ("fly", "FlyIOBackend"),
        ],
    )
    @pytest.mark.asyncio
    async def test_autoscaler_backend_selection(
        self,
        orchestrator: str,
        expected_backend: str,
        fake_redis_client: FakeRedisClient,
    ) -> None:
        """Test that autoscaler selects the correct backend."""
        autoscaler = WorkerAutoscaler(
            redis_url="redis://fake",
            orchestrator=orchestrator,
        )

        with patch("redis.asyncio.from_url") as mock_from_url:
            mock_from_url.return_value = fake_redis_client

            # For Fly.io, set required env var
            if orchestrator == "fly":
                with patch.dict("os.environ", {"FLY_APP_NAME": "test-app"}):
                    await autoscaler.setup()
            else:
                await autoscaler.setup()

            # Verify correct backend was created
            assert autoscaler.scaling_service is not None
            assert autoscaler.scaling_service.backend is not None
            backend_type = type(autoscaler.scaling_service.backend).__name__
            assert backend_type == expected_backend


class TestAutoscalerMain:
    """Test the autoscaler main entry point."""

    @pytest.mark.asyncio
    async def test_main_function_integration(self) -> None:
        """Test the main function with mocked components."""
        from scripts.autoscaler import main

        # Mock command line args
        test_args = [
            "--redis-url",
            "redis://localhost:6379",
            "--orchestrator",
            "docker",
            "--check-interval",
            "1",
        ]

        with patch("sys.argv", ["autoscaler.py"] + test_args):
            with patch("scripts.autoscaler.WorkerAutoscaler") as mock_autoscaler_class:
                # Create a mock autoscaler instance
                mock_autoscaler = AsyncMock()
                mock_autoscaler_class.return_value = mock_autoscaler

                # Run main (with quick interruption)
                async def interrupt_main() -> None:
                    await asyncio.sleep(0.1)
                    raise KeyboardInterrupt()

                asyncio.create_task(interrupt_main())

                try:
                    await main()
                except KeyboardInterrupt:
                    pass

                # Verify autoscaler was created with correct params
                mock_autoscaler_class.assert_called_once_with(
                    redis_url="redis://localhost:6379",
                    orchestrator="docker",
                    check_interval=1,
                )

                # Verify lifecycle methods were called
                mock_autoscaler.setup.assert_called_once()
                mock_autoscaler.run.assert_called_once()
                mock_autoscaler.cleanup.assert_called_once()
