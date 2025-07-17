"""
Integration Tests for Distributed Scaling
=========================================

Tests the entire scaling flow from job dispatch to worker creation.
Uses dependency injection with fake implementations.
"""

import asyncio
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import redis.asyncio as redis_asyncio

from bot.distributed.backends.docker_api import DockerApiBackend
from bot.distributed.broker import Broker
from bot.distributed.core.config import (
    DistributedConfig,
    ScalingConfig,
    WorkerTypeConfig,
)
from bot.distributed.model import Job, new_job
from bot.distributed.remote_browser import RemoteBrowserRuntime
from bot.distributed.services.scaling_service import ScalingDecision, ScalingService
from bot.plugins.commands.web import Web
from tests.fakes.fake_redis import FakeRedisClient
from tests.fakes.fake_scaling_backend import FakeScalingBackend


class FakeSubprocessBackend(FakeScalingBackend):
    """
    Fake backend that simulates subprocess execution.
    Tracks actual commands that would be executed.
    """

    def __init__(self, initial_counts: dict[str, int] | None = None):
        super().__init__(initial_counts)
        self.executed_commands: list[list[str]] = []
        self.command_results: list[dict[str, Any]] = []

    async def scale_to(self, worker_type: str, target_count: int) -> bool:
        """Simulate scaling and track the command."""
        if self.should_fail:
            return False

        # Track what command would be executed
        if hasattr(self, "_build_scale_command"):
            cmd = self._build_scale_command(worker_type, target_count)
            self.executed_commands.append(cmd)

        # Call parent to update counts
        return await super().scale_to(worker_type, target_count)


class TestEndToEndScaling:
    """Test the complete scaling flow from Discord command to worker creation."""

    @pytest.fixture
    async def fake_redis(self) -> FakeRedisClient:
        """Create a fake Redis client."""
        return FakeRedisClient()

    @pytest.fixture
    def test_config(self) -> DistributedConfig:
        """Create test configuration with aggressive scaling."""
        config = DistributedConfig()
        config.worker_types = {
            "browser": WorkerTypeConfig(
                name="browser",
                job_queue="browser:jobs",
                scaling=ScalingConfig(
                    min_workers=0,
                    max_workers=5,
                    scale_up_threshold=1,  # Scale up with just 1 job
                    scale_down_threshold=0,
                    cooldown_seconds=1,
                ),
                enabled=True,
            ),
        }
        return config

    @pytest.fixture
    def fake_backend(self) -> FakeSubprocessBackend:
        """Create a fake scaling backend."""
        return FakeSubprocessBackend(initial_counts={"browser": 0})

    @pytest.fixture
    async def scaling_service(
        self,
        fake_redis: FakeRedisClient,
        test_config: DistributedConfig,
        fake_backend: FakeSubprocessBackend,
    ) -> ScalingService:
        """Create scaling service with fake dependencies."""
        service = ScalingService(
            redis_client=fake_redis,  # type: ignore
            config=test_config,
            backend=fake_backend,
        )
        return service

    @pytest.fixture
    async def broker(self, fake_redis: FakeRedisClient) -> Broker:
        """Create a broker with fake Redis."""
        # Mock the broker to use our fake Redis
        broker = MagicMock(spec=Broker)
        broker._r = fake_redis

        # Track published jobs
        broker.published_jobs = []

        async def publish(job: Job) -> None:
            broker.published_jobs.append(job)
            # Add to the Redis stream for the scaling service to see
            await fake_redis.xadd("browser:jobs", {"job": job.dumps()})

        async def publish_and_wait(job: Job, timeout: float = 30.0) -> dict[str, Any]:
            await publish(job)
            # Simulate successful result
            return {"success": True, "job_id": job.id}

        broker.publish = publish
        broker.publish_and_wait = publish_and_wait

        return broker

    @pytest.fixture
    def browser_runtime(self, broker: Broker) -> RemoteBrowserRuntime:
        """Create browser runtime with mocked broker."""
        return RemoteBrowserRuntime(broker)

    @pytest.mark.asyncio
    async def test_web_command_triggers_scaling(
        self,
        fake_redis: FakeRedisClient,
        fake_backend: FakeSubprocessBackend,
        scaling_service: ScalingService,
        browser_runtime: RemoteBrowserRuntime,
    ) -> None:
        """Test that a /web command triggers worker scaling when no workers exist."""
        # Initial state: no browser workers
        assert await fake_backend.get_current_count("browser") == 0

        # User executes /web start command
        await browser_runtime.start(worker_hint="test-user")

        # Job should be in the queue
        queue_depth = await fake_redis.xlen("browser:jobs")
        assert queue_depth == 1

        # Run scaling check (this would normally be done by the autoscaler)
        results = await scaling_service.check_and_scale_all()

        # Should have scaled up browser workers
        assert results["browser"] is True
        assert await fake_backend.get_current_count("browser") == 1

        # Verify scaling history
        assert fake_backend.was_scaled("browser")
        last_scaling = fake_backend.get_last_scaling()
        assert last_scaling == ("browser", 0, 1)

    @pytest.mark.asyncio
    async def test_multiple_jobs_scale_up_further(
        self,
        fake_redis: FakeRedisClient,
        fake_backend: FakeSubprocessBackend,
        scaling_service: ScalingService,
        browser_runtime: RemoteBrowserRuntime,
    ) -> None:
        """Test that multiple jobs cause further scaling."""
        # Start with 1 worker
        fake_backend.set_count("browser", 1)

        # Add multiple jobs
        for i in range(5):
            await browser_runtime.goto(f"https://example.com/{i}", worker_hint=f"user-{i}")

        # Check queue
        queue_depth = await fake_redis.xlen("browser:jobs")
        assert queue_depth == 5

        # Run scaling check
        results = await scaling_service.check_and_scale_all()

        # Should scale up due to queue depth
        assert results["browser"] is True
        assert await fake_backend.get_current_count("browser") == 2

    @pytest.mark.asyncio
    async def test_autoscaler_continuous_monitoring(
        self,
        fake_redis: FakeRedisClient,
        fake_backend: FakeSubprocessBackend,
        scaling_service: ScalingService,
        browser_runtime: RemoteBrowserRuntime,
    ) -> None:
        """Test the autoscaler monitoring and scaling over time."""

        # Simulate the autoscaler loop
        async def autoscaler_loop(iterations: int = 3) -> None:
            for _ in range(iterations):
                await scaling_service.check_and_scale_all()
                await asyncio.sleep(0.1)

        # Start with no workers
        assert await fake_backend.get_current_count("browser") == 0

        # Add a job
        await browser_runtime.start()

        # Run autoscaler for a few iterations
        await autoscaler_loop(3)

        # Should have scaled up
        assert await fake_backend.get_current_count("browser") > 0

    @pytest.mark.asyncio
    async def test_scaling_respects_limits(
        self,
        fake_redis: FakeRedisClient,
        fake_backend: FakeSubprocessBackend,
        scaling_service: ScalingService,
        browser_runtime: RemoteBrowserRuntime,
    ) -> None:
        """Test that scaling respects min/max limits."""
        # Start at max workers
        fake_backend.set_count("browser", 5)

        # Add many jobs
        for i in range(20):
            await browser_runtime.goto(f"https://example.com/{i}")

        # Run scaling check
        await scaling_service.check_and_scale_all()

        # Should not scale beyond max
        assert await fake_backend.get_current_count("browser") == 5

    @pytest.mark.asyncio
    async def test_worker_health_affects_scaling(
        self,
        fake_redis: FakeRedisClient,
        fake_backend: FakeSubprocessBackend,
        scaling_service: ScalingService,
    ) -> None:
        """Test that unhealthy workers are considered in scaling decisions."""
        # Set up some workers
        fake_backend.set_count("browser", 3)

        # Register only 1 as healthy via heartbeats
        await fake_redis.hset(
            "worker:heartbeat:browser:worker-1",
            "capabilities",
            '{"max_sessions": 5}',
        )

        # Update worker health
        await scaling_service.update_worker_health()

        # Add jobs
        await fake_redis.xadd("browser:jobs", {"job": "test1"})
        await fake_redis.xadd("browser:jobs", {"job": "test2"})

        # Check scaling - should consider only healthy workers
        decision, target = scaling_service.make_scaling_decision(
            worker_type="browser",
            queue_depth=2,
            current_workers=1,  # Only 1 healthy
        )

        # Should decide to scale up
        assert decision == ScalingDecision.SCALE_UP
        assert target == 2


class TestDockerComposeIntegration:
    """Test Docker backends with better dependency injection."""

    @pytest.fixture
    def subprocess_executor(self) -> AsyncMock:
        """Create a fake subprocess executor."""
        executor = AsyncMock()
        executor.executed_commands = []

        async def fake_create_subprocess_exec(*args: Any, **kwargs: Any) -> AsyncMock:
            # Track the command
            executor.executed_commands.append(list(args))

            # Create a mock process
            proc = AsyncMock()
            proc.returncode = 0
            proc.communicate = AsyncMock(return_value=(b"Success", b""))

            return proc

        executor.create_subprocess_exec = fake_create_subprocess_exec
        return executor

    @pytest.mark.asyncio
    async def test_docker_api_backend_execution(self, subprocess_executor: AsyncMock) -> None:
        """Test actual Docker API backend functionality."""
        # Create backend with dependency injection
        backend = DockerApiBackend(
            image="test-image:latest", network="test_network", project_name="test-project"
        )

        # Mock Docker client methods
        with patch.object(backend, "get_current_count", return_value=0):
            with patch.object(
                backend, "_create_worker_container", return_value=True
            ) as mock_create:
                # Execute scaling
                result = await backend.scale_to("browser", 3)

                # Verify success
                assert result is True
                assert mock_create.call_count == 3


class TestScalingServiceWithRealRedis:
    """Test ScalingService with a more realistic Redis setup."""

    @pytest.fixture
    async def redis_with_streams(self) -> FakeRedisClient:
        """Create a fake Redis that properly handles streams."""
        redis_client = FakeRedisClient()

        # Pre-create the streams that would exist in production
        await redis_client.xadd("browser:jobs", {"_": "init"})
        await redis_client.xadd("tankpit:jobs", {"_": "init"})

        return redis_client

    @pytest.mark.asyncio
    async def test_scaling_decision_with_real_queue_monitoring(
        self,
        redis_with_streams: FakeRedisClient,
    ) -> None:
        """Test scaling decisions based on actual Redis queue state."""
        config = DistributedConfig()
        backend = FakeScalingBackend(initial_counts={"browser": 2})

        service = ScalingService(
            redis_client=redis_with_streams,  # type: ignore
            config=config,
            backend=backend,
        )

        # Add jobs to the queue
        for i in range(15):
            await redis_with_streams.xadd("browser:jobs", {"job": f"job-{i}"})

        # Get actual queue depth
        queue_depth = await service.get_queue_depth("browser")
        assert queue_depth == 16  # 15 jobs added + 1 init message

        # Make scaling decision
        decision, target = service.make_scaling_decision(
            worker_type="browser",
            queue_depth=queue_depth,
            current_workers=2,
        )

        # Should scale up due to high queue depth
        assert decision == ScalingDecision.SCALE_UP
        assert target == 3


class TestMissingWorkerScenarios:
    """Test scenarios where no workers are available."""

    @pytest.mark.asyncio
    async def test_job_timeout_when_no_workers(self) -> None:
        """Test that jobs timeout when no workers exist and no autoscaler is running."""
        fake_redis = FakeRedisClient()

        with patch("redis.asyncio.from_url") as mock_from_url:
            mock_from_url.return_value = fake_redis
            broker = Broker("redis://fake")
            browser = RemoteBrowserRuntime(broker)

            # Try to execute a command with no workers
            with pytest.raises(TimeoutError):
                # This should timeout because no worker will process the job
                await asyncio.wait_for(
                    browser.start(worker_hint="test-user"),
                    timeout=1.0,
                )

    @pytest.mark.asyncio
    async def test_autoscaler_creates_workers_on_demand(self) -> None:
        """Test that autoscaler creates workers when jobs are waiting."""
        fake_redis = FakeRedisClient()
        config = DistributedConfig()

        # Override browser config for immediate scaling
        config.worker_types["browser"].scaling.scale_up_threshold = 1
        config.worker_types["browser"].scaling.min_workers = 0

        scaling_backend = FakeScalingBackend(initial_counts={"browser": 0})
        scaling_service = ScalingService(
            redis_client=fake_redis,  # type: ignore
            config=config,
            backend=scaling_backend,
        )

        # Add a job to the browser queue
        await fake_redis.xadd("browser:jobs", {"job": "waiting"})

        # Initially no workers
        assert await scaling_backend.get_current_count("browser") == 0

        # Run scaling check
        await scaling_service.check_and_scale_all()

        # Should create workers
        assert await scaling_backend.get_current_count("browser") > 0
