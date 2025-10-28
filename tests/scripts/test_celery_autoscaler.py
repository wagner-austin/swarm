"""Tests for the Celery autoscaler without Flower (Redis + Inspect)."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scripts.celery_autoscaler import CeleryAutoscaler
from swarm.distributed.protocols import ScalingDecision


class TestCeleryAutoscaler:
    """Test the Celery autoscaler."""

    @pytest.fixture
    def mock_config(self) -> MagicMock:
        """Create mock distributed config."""
        config = MagicMock()

        # Mock worker type config
        browser_config = MagicMock()
        browser_config.enabled = True
        browser_config.job_queue = "browser:jobs"
        browser_config.scaling.min_workers = 1
        browser_config.scaling.max_workers = 5
        browser_config.scaling.scale_up_threshold = 3
        browser_config.scaling.scale_down_threshold = 0

        config.worker_types = {"browser": browser_config}
        config.get_enabled_worker_types.return_value = ["browser"]

        return config

    @pytest.fixture
    def mock_backend(self) -> AsyncMock:
        """Create mock scaling backend."""
        backend = AsyncMock()
        backend.get_current_count.return_value = 2
        backend.scale_to.return_value = True
        return backend

    # No aiohttp session – autoscaler no longer uses Flower

    @pytest.mark.asyncio
    async def test_happy_path_scale_up(
        self,
        mock_config: MagicMock,
        mock_backend: AsyncMock,
    ) -> None:
        """Test autoscaler scales up when queue depth exceeds threshold."""
        autoscaler = CeleryAutoscaler(orchestrator="docker-api")

        # Inject mocks
        autoscaler.config = mock_config
        autoscaler.backend = mock_backend
        # Queue has depth 5, threshold is 3; current workers 2 → scale to 3
        with patch.object(
            CeleryAutoscaler,
            "get_queue_stats",
            new=AsyncMock(return_value={"browser": {"depth": 5}}),
        ):
            await autoscaler.check_and_scale()

        # Verify scaling decision
        mock_backend.scale_to.assert_called_once_with("browser", 3)

    @pytest.mark.asyncio
    async def test_scale_down_empty_queue(
        self,
        mock_config: MagicMock,
        mock_backend: AsyncMock,
    ) -> None:
        """Test autoscaler scales down when queue is empty."""
        autoscaler = CeleryAutoscaler()

        # Inject mocks
        autoscaler.config = mock_config
        autoscaler.backend = mock_backend
        # Current workers: 2, queue depth 0 → scale down to 1 (min)
        with patch.object(
            CeleryAutoscaler,
            "get_queue_stats",
            new=AsyncMock(return_value={"browser": {"depth": 0}}),
        ):
            await autoscaler.check_and_scale()

        mock_backend.scale_to.assert_called_once_with("browser", 1)

    def test_make_scaling_decision_scale_up(self, mock_config: MagicMock) -> None:
        """Test scaling decision logic for scale up."""
        autoscaler = CeleryAutoscaler()
        browser_config = mock_config.worker_types["browser"]

        # Queue depth 5, current workers 2, threshold 3
        decision, target = autoscaler.make_scaling_decision("browser", 5, 2, browser_config)

        assert decision == ScalingDecision.SCALE_UP
        assert target == 3

    def test_make_scaling_decision_at_max(self, mock_config: MagicMock) -> None:
        """Test scaling decision when at max workers."""
        autoscaler = CeleryAutoscaler()
        browser_config = mock_config.worker_types["browser"]

        # Queue depth 10, but already at max workers (5)
        decision, target = autoscaler.make_scaling_decision("browser", 10, 5, browser_config)

        assert decision == ScalingDecision.NO_CHANGE
        assert target == 5

    def test_make_scaling_decision_ensure_minimum(self, mock_config: MagicMock) -> None:
        """Test scaling decision ensures minimum workers."""
        autoscaler = CeleryAutoscaler()
        browser_config = mock_config.worker_types["browser"]

        # 0 workers, should scale up to minimum (1)
        decision, target = autoscaler.make_scaling_decision("browser", 0, 0, browser_config)

        assert decision == ScalingDecision.SCALE_UP
        assert target == 1

    @pytest.mark.asyncio
    async def test_aggregates_base_and_direct_queues(
        self, mock_config: MagicMock, mock_backend: AsyncMock
    ) -> None:
        autoscaler = CeleryAutoscaler(orchestrator="docker-api")
        autoscaler.config = mock_config
        autoscaler.backend = mock_backend

        async def fake_get_queue_stats() -> dict[str, dict[str, int]]:
            # Simulate aggregated depth: base=1, direct=2 => total=3
            return {"browser": {"depth": 3}}

        with patch.object(
            CeleryAutoscaler,
            "get_queue_stats",
            new=AsyncMock(return_value={"browser": {"depth": 3}}),
        ):
            await autoscaler.check_and_scale()
        mock_backend.scale_to.assert_called_once_with("browser", 3)
