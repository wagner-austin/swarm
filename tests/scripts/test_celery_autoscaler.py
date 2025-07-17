"""Tests for the Celery autoscaler using Flower API."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from scripts.celery_autoscaler import CeleryAutoscaler
from swarm.distributed.services.scaling_service import ScalingDecision


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

    @pytest.fixture
    def mock_session(self) -> MagicMock:
        """Create mock aiohttp session."""
        session = MagicMock()

        # Mock queue stats response
        queue_response = AsyncMock()
        queue_response.status = 200
        queue_response.json.return_value = {
            "active_queues": [
                {
                    "name": "browser",
                    "messages": 5,
                    "messages_ready": 4,
                    "messages_unacknowledged": 1,
                }
            ]
        }

        # Mock worker stats response
        worker_response = AsyncMock()
        worker_response.status = 200
        worker_response.json.return_value = {
            "worker1": {"active_queues": [{"name": "browser"}]},
            "worker2": {"active_queues": [{"name": "browser"}]},
        }

        # Configure get to return appropriate response
        async def mock_get(url: str, **kwargs: Any) -> Any:
            if "queues/length" in url:
                return queue_response
            elif "workers" in url:
                return worker_response
            return AsyncMock(status=404)

        session.get = mock_get
        return session

    @pytest.mark.asyncio
    async def test_happy_path_scale_up(
        self,
        mock_config: MagicMock,
        mock_backend: AsyncMock,
        mock_session: MagicMock,
    ) -> None:
        """Test autoscaler scales up when queue depth exceeds threshold."""
        autoscaler = CeleryAutoscaler(
            flower_url="http://localhost:5555",
            orchestrator="docker-api",
        )

        # Inject mocks
        autoscaler.config = mock_config
        autoscaler.backend = mock_backend
        autoscaler._session = mock_session

        # Queue has 5 messages (4 ready + 1 unacked), threshold is 3
        # Current workers: 2, should scale up to 3
        await autoscaler.check_and_scale()

        # Verify scaling decision
        mock_backend.scale_to.assert_called_once_with("browser", 3)

    @pytest.mark.asyncio
    async def test_scale_down_empty_queue(
        self,
        mock_config: MagicMock,
        mock_backend: AsyncMock,
        mock_session: MagicMock,
    ) -> None:
        """Test autoscaler scales down when queue is empty."""
        autoscaler = CeleryAutoscaler()

        # Inject mocks
        autoscaler.config = mock_config
        autoscaler.backend = mock_backend
        autoscaler._session = mock_session

        # Override the mock session to return empty queue
        empty_response = AsyncMock()
        empty_response.status = 200
        empty_response.json.return_value = {
            "active_queues": [
                {
                    "name": "browser",
                    "messages": 0,
                    "messages_ready": 0,
                    "messages_unacknowledged": 0,
                }
            ]
        }

        async def mock_get_empty(url: str, **kwargs: Any) -> Any:
            if "queues/length" in url:
                return empty_response
            return AsyncMock(status=404)

        mock_session.get = mock_get_empty

        # Current workers: 2, should scale down to 1 (min)
        await autoscaler.check_and_scale()

        mock_backend.scale_to.assert_called_once_with("browser", 1)

    @pytest.mark.asyncio
    async def test_flower_api_timeout(
        self,
        mock_config: MagicMock,
        mock_backend: AsyncMock,
    ) -> None:
        """Test autoscaler handles Flower API timeouts gracefully."""
        autoscaler = CeleryAutoscaler()

        # Create session that times out
        mock_session = MagicMock()

        async def timeout_get(*args: Any, **kwargs: Any) -> None:
            raise TimeoutError()

        mock_session.get = timeout_get

        # Inject mocks
        autoscaler.config = mock_config
        autoscaler.backend = mock_backend
        autoscaler._session = mock_session

        # Should not raise, just log error
        await autoscaler.check_and_scale()

        # Should scale to min_workers even without queue data (to support bootstrapping)
        mock_backend.scale_to.assert_called_once_with("browser", 1)

    @pytest.mark.asyncio
    async def test_auth_configuration(self) -> None:
        """Test autoscaler configures basic auth when credentials provided."""
        autoscaler = CeleryAutoscaler(
            flower_username="admin",
            flower_password="secret",
        )

        with patch("aiohttp.ClientSession"):
            await autoscaler.setup()

        assert autoscaler._auth is not None
        assert autoscaler._auth.login == "admin"
        assert autoscaler._auth.password == "secret"

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
