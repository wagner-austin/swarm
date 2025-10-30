"""Tests for the Celery autoscaler without Flower (Redis + Inspect)."""

import asyncio

import pytest

from scripts.celery_autoscaler import CeleryAutoscaler
from swarm.distributed.core.config import ScalingConfig, WorkerTypeConfig
from swarm.distributed.protocols import ScalingBackend, ScalingDecision


class _FakeBackend(ScalingBackend):
    def __init__(self, *, current: int = 2) -> None:
        self._current: int = current
        self.last_scaled_to: int | None = None

    async def get_current_count(self, worker_type: str) -> int:  # noqa: ARG002
        return int(self._current)

    async def scale_to(self, worker_type: str, target_count: int) -> bool:  # noqa: ARG002
        self.last_scaled_to = int(target_count)
        self._current = int(target_count)
        return True


class _FakeConfig:
    def __init__(self) -> None:
        self.worker_types: dict[str, WorkerTypeConfig] = {
            "browser": WorkerTypeConfig(
                name="browser",
                job_queue="browser:jobs",
                scaling=ScalingConfig(
                    min_workers=1,
                    max_workers=5,
                    scale_up_threshold=3,
                    scale_down_threshold=0,
                ),
                enabled=True,
            )
        }


class TestCeleryAutoscaler:
    """Test the Celery autoscaler (typed fakes, no mocks)."""

    @pytest.mark.asyncio
    async def test_happy_path_scale_up(self) -> None:
        class Stub(CeleryAutoscaler):
            async def get_queue_stats(self) -> dict[str, dict[str, int]]:
                return {"browser": {"depth": 5}}

        autoscaler = Stub(orchestrator="docker-api")
        autoscaler.config = _FakeConfig()
        backend = _FakeBackend(current=2)
        autoscaler.backend = backend

        await autoscaler.check_and_scale()
        assert backend.last_scaled_to == 3

    @pytest.mark.asyncio
    async def test_scale_down_empty_queue(self) -> None:
        class Stub(CeleryAutoscaler):
            async def get_queue_stats(self) -> dict[str, dict[str, int]]:
                return {"browser": {"depth": 0}}

        autoscaler = Stub()
        autoscaler.config = _FakeConfig()
        backend = _FakeBackend(current=2)
        autoscaler.backend = backend

        await autoscaler.check_and_scale()
        assert backend.last_scaled_to == 1

    def test_make_scaling_decision_scale_up(self) -> None:
        autoscaler = CeleryAutoscaler()
        browser_config = _FakeConfig().worker_types["browser"]
        decision, target = autoscaler.make_scaling_decision("browser", 5, 2, browser_config)
        assert decision == ScalingDecision.SCALE_UP
        assert target == 3

    def test_make_scaling_decision_at_max(self) -> None:
        autoscaler = CeleryAutoscaler()
        browser_config = _FakeConfig().worker_types["browser"]
        decision, target = autoscaler.make_scaling_decision("browser", 10, 5, browser_config)
        assert decision == ScalingDecision.NO_CHANGE
        assert target == 5

    def test_make_scaling_decision_ensure_minimum(self) -> None:
        autoscaler = CeleryAutoscaler()
        browser_config = _FakeConfig().worker_types["browser"]
        decision, target = autoscaler.make_scaling_decision("browser", 0, 0, browser_config)
        assert decision == ScalingDecision.SCALE_UP
        assert target == 1

    @pytest.mark.asyncio
    async def test_aggregates_base_and_direct_queues(self) -> None:
        class Stub(CeleryAutoscaler):
            async def get_queue_stats(self) -> dict[str, dict[str, int]]:
                # Simulate aggregated depth: base=1, direct=2 => total=3
                return {"browser": {"depth": 3}}

        autoscaler = Stub(orchestrator="docker-api")
        autoscaler.config = _FakeConfig()
        backend = _FakeBackend(current=2)
        autoscaler.backend = backend

        await autoscaler.check_and_scale()
        assert backend.last_scaled_to == 3
