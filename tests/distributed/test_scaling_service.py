"""
Tests for Scaling Service
=========================

Tests the scaling service using fake backends and real Redis.
"""

import asyncio
import time
from typing import Any, cast

import pytest
import redis.asyncio as redis_asyncio

from bot.distributed.core.config import (
    DistributedConfig,
    ScalingConfig,
    WorkerTypeConfig,
)
from bot.distributed.services.scaling_service import (
    ScalingDecision,
    ScalingService,
)
from tests.fakes.fake_redis import FakeRedisClient
from tests.fakes.fake_scaling_backend import FakeScalingBackend


@pytest.fixture
def fake_redis() -> FakeRedisClient:
    """Create a fake Redis client."""
    return FakeRedisClient()


@pytest.fixture
def test_config() -> DistributedConfig:
    """Create a test configuration."""
    config = DistributedConfig()
    # Override with test-friendly values
    config.worker_types = {
        "test": WorkerTypeConfig(
            name="test",
            job_queue="test:jobs",
            scaling=ScalingConfig(
                min_workers=1,
                max_workers=5,
                scale_up_threshold=3,
                scale_down_threshold=1,
                cooldown_seconds=1,  # Short for testing
            ),
        ),
    }
    config.worker_health_timeout = 30
    return config


@pytest.fixture
def fake_backend() -> FakeScalingBackend:
    """Create a fake scaling backend."""
    return FakeScalingBackend(initial_counts={"test": 2})


@pytest.mark.asyncio
class TestScalingService:
    """Test the ScalingService class."""

    async def test_service_creation(
        self, fake_redis: FakeRedisClient, test_config: DistributedConfig
    ) -> None:
        """Test creating a scaling service."""
        service = ScalingService(cast(redis_asyncio.Redis, fake_redis), test_config)

        assert service.config == test_config
        assert service.backend is None
        assert "test" in service.pools

    async def test_get_queue_depth(
        self, fake_redis: FakeRedisClient, test_config: DistributedConfig
    ) -> None:
        """Test getting queue depth from Redis."""
        service = ScalingService(cast(redis_asyncio.Redis, fake_redis), test_config)

        # Add some jobs to the queue
        await fake_redis.xadd("test:jobs", {"job": "1"})
        await fake_redis.xadd("test:jobs", {"job": "2"})
        await fake_redis.xadd("test:jobs", {"job": "3"})

        depth = await service.get_queue_depth("test")
        assert depth == 3

    async def test_get_queue_depth_missing_type(
        self, fake_redis: FakeRedisClient, test_config: DistributedConfig
    ) -> None:
        """Test getting queue depth for missing worker type."""
        service = ScalingService(cast(redis_asyncio.Redis, fake_redis), test_config)

        depth = await service.get_queue_depth("nonexistent")
        assert depth == 0

    async def test_update_worker_health(
        self, fake_redis: FakeRedisClient, test_config: DistributedConfig
    ) -> None:
        """Test updating worker health from Redis."""
        service = ScalingService(cast(redis_asyncio.Redis, fake_redis), test_config)

        # Simulate worker heartbeats
        await fake_redis.hset(
            "worker:heartbeat:test:worker-1",
            "state",
            "IDLE",
        )
        await fake_redis.hset(
            "worker:heartbeat:test:worker-2",
            "state",
            "BUSY",
        )

        # Update health
        await service.update_worker_health()

        # Check pool was updated
        pool = service.pools["test"]
        assert len(pool.workers) == 2
        assert "worker-1" in pool.workers
        assert "worker-2" in pool.workers

    async def test_make_scaling_decision_scale_up(
        self, fake_redis: FakeRedisClient, test_config: DistributedConfig
    ) -> None:
        """Test making a scale up decision."""
        service = ScalingService(cast(redis_asyncio.Redis, fake_redis), test_config)

        # High queue depth, few workers
        decision, target = service.make_scaling_decision(
            worker_type="test",
            queue_depth=5,  # Above threshold of 3
            current_workers=2,
        )

        assert decision == ScalingDecision.SCALE_UP
        assert target == 3  # Current + 1

    async def test_make_scaling_decision_scale_down(
        self, fake_redis: FakeRedisClient, test_config: DistributedConfig
    ) -> None:
        """Test making a scale down decision."""
        service = ScalingService(cast(redis_asyncio.Redis, fake_redis), test_config)

        # Low queue depth, many workers
        decision, target = service.make_scaling_decision(
            worker_type="test",
            queue_depth=0,  # Below threshold of 1
            current_workers=3,
        )

        assert decision == ScalingDecision.SCALE_DOWN
        assert target == 2  # Current - 1

    async def test_make_scaling_decision_no_change(
        self, fake_redis: FakeRedisClient, test_config: DistributedConfig
    ) -> None:
        """Test making a no change decision."""
        service = ScalingService(cast(redis_asyncio.Redis, fake_redis), test_config)

        # Queue depth between thresholds
        decision, target = service.make_scaling_decision(
            worker_type="test",
            queue_depth=2,  # Between 1 and 3
            current_workers=2,
        )

        assert decision == ScalingDecision.NO_CHANGE
        assert target == 2

    async def test_make_scaling_decision_respects_limits(
        self, fake_redis: FakeRedisClient, test_config: DistributedConfig
    ) -> None:
        """Test that scaling respects min/max limits."""
        service = ScalingService(cast(redis_asyncio.Redis, fake_redis), test_config)

        # Try to scale above max
        decision, target = service.make_scaling_decision(
            worker_type="test",
            queue_depth=10,
            current_workers=5,  # Already at max
        )

        assert decision == ScalingDecision.NO_CHANGE
        assert target == 5

        # Try to scale below min
        decision, target = service.make_scaling_decision(
            worker_type="test",
            queue_depth=0,
            current_workers=1,  # Already at min
        )

        assert decision == ScalingDecision.NO_CHANGE
        assert target == 1

    async def test_make_scaling_decision_cooldown(
        self, fake_redis: FakeRedisClient, test_config: DistributedConfig
    ) -> None:
        """Test that scale-up ignores cooldown, but scale-down respects it."""
        service = ScalingService(cast(redis_asyncio.Redis, fake_redis), test_config)

        # Record a recent scaling operation
        service.last_scale_time["test"] = time.time() - 0.5  # 0.5 seconds ago

        # Scale-up should ignore cooldown (queue_depth=5 > scale_up_threshold=3)
        decision, target = service.make_scaling_decision(
            worker_type="test",
            queue_depth=5,
            current_workers=2,
        )

        assert decision == ScalingDecision.SCALE_UP
        assert target == 3

        # Scale-down should respect cooldown
        decision, target = service.make_scaling_decision(
            worker_type="test",
            queue_depth=0,  # Below scale_down_threshold=1
            current_workers=3,
        )

        assert decision == ScalingDecision.NO_CHANGE  # Blocked by cooldown
        assert target == 3

    async def test_execute_scaling_no_change(
        self,
        fake_redis: FakeRedisClient,
        test_config: DistributedConfig,
        fake_backend: FakeScalingBackend,
    ) -> None:
        """Test executing a no-change decision."""
        service = ScalingService(cast(redis_asyncio.Redis, fake_redis), test_config, fake_backend)

        success = await service.execute_scaling("test", ScalingDecision.NO_CHANGE, 2)

        assert success is True
        assert not fake_backend.was_scaled("test")

    async def test_execute_scaling_scale_up(
        self,
        fake_redis: FakeRedisClient,
        test_config: DistributedConfig,
        fake_backend: FakeScalingBackend,
    ) -> None:
        """Test executing a scale up."""
        service = ScalingService(cast(redis_asyncio.Redis, fake_redis), test_config, fake_backend)

        success = await service.execute_scaling("test", ScalingDecision.SCALE_UP, 3)

        assert success is True
        assert fake_backend.was_scaled("test")

        last_op = fake_backend.get_last_scaling()
        assert last_op == ("test", 2, 3)  # From 2 to 3

        # Check tracking was updated
        assert "test" in service.last_scale_time
        assert len(service.scaling_history) == 1

    async def test_execute_scaling_failure(
        self,
        fake_redis: FakeRedisClient,
        test_config: DistributedConfig,
        fake_backend: FakeScalingBackend,
    ) -> None:
        """Test handling scaling failure."""
        service = ScalingService(cast(redis_asyncio.Redis, fake_redis), test_config, fake_backend)

        # Make backend fail
        fake_backend.should_fail = True

        success = await service.execute_scaling("test", ScalingDecision.SCALE_UP, 3)

        assert success is False
        assert "test" not in service.last_scale_time

    async def test_check_and_scale_all(
        self,
        fake_redis: FakeRedisClient,
        test_config: DistributedConfig,
        fake_backend: FakeScalingBackend,
    ) -> None:
        """Test checking and scaling all worker types."""
        service = ScalingService(cast(redis_asyncio.Redis, fake_redis), test_config, fake_backend)

        # Set up conditions for scaling
        # Add jobs to trigger scale up
        for _ in range(5):
            await fake_redis.xadd("test:jobs", {"job": "data"})

        # Add worker heartbeats
        await fake_redis.hset(
            "worker:heartbeat:test:worker-1",
            "capabilities",
            '{"type": "test"}',
        )
        await fake_redis.hset(
            "worker:heartbeat:test:worker-2",
            "capabilities",
            '{"type": "test"}',
        )

        # Check and scale
        results = await service.check_and_scale_all()

        assert results["test"] is True
        assert fake_backend.was_scaled("test")

        # Should have scaled from 2 to 3
        last_op = fake_backend.get_last_scaling()
        assert last_op == ("test", 2, 3)

    async def test_get_metrics(
        self, fake_redis: FakeRedisClient, test_config: DistributedConfig
    ) -> None:
        """Test getting service metrics."""
        service = ScalingService(cast(redis_asyncio.Redis, fake_redis), test_config)

        # Add some history
        service.scaling_history.append(
            {
                "timestamp": time.time(),
                "worker_type": "test",
                "decision": "scale_up",
                "from_count": 1,
                "to_count": 2,
                "success": True,
            }
        )

        metrics = service.get_metrics()

        assert "pools" in metrics
        assert "test" in metrics["pools"]
        assert "last_scale_times" in metrics
        assert metrics["scaling_history_count"] == 1
        assert len(metrics["recent_scaling_events"]) == 1

    async def test_scaling_event_recording(
        self,
        fake_redis: FakeRedisClient,
        test_config: DistributedConfig,
        fake_backend: FakeScalingBackend,
    ) -> None:
        """Test that scaling events are recorded in Redis."""
        service = ScalingService(cast(redis_asyncio.Redis, fake_redis), test_config, fake_backend)

        # Execute a scaling operation
        await service.execute_scaling("test", ScalingDecision.SCALE_UP, 3)

        # Check event was recorded
        events = await fake_redis.xrange("scaling:events")
        assert len(events) == 1

        event_data = events[0][1]
        assert event_data["worker_type"] == "test"
        assert event_data["decision"] == "scale_up"
        assert event_data["from_count"] == "2"
        assert event_data["to_count"] == "3"
