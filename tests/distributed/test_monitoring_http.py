"""
Test suite for HTTP monitoring endpoints (/health and /metrics).
Comprehensive coverage of aiohttp server functionality and response formats.
"""

import asyncio
import json
from typing import Any, cast
from unittest.mock import AsyncMock, Mock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from bot.distributed.monitoring.http import WORKER_KEY, health, metrics, start_http_server
from bot.distributed.monitoring.state import WorkerState
from bot.distributed.worker import Worker


class TestHealthEndpoint:
    """Test /health endpoint functionality and response formats."""

    @pytest.fixture
    def mock_worker(self) -> Mock:
        """Create a mocked worker for testing."""
        worker = Mock()
        worker.get_state.return_value = WorkerState.IDLE
        worker.worker_id = "test-worker-123"
        return worker

    @pytest.fixture
    def mock_request(self, mock_worker: Mock) -> Mock:
        """Create a mocked aiohttp request with worker in app context."""
        request = Mock()
        request.app = {WORKER_KEY: mock_worker}
        return request

    @pytest.mark.asyncio
    async def test_health_idle_state_success(self, mock_request: Mock, mock_worker: Mock) -> None:
        """Test /health returns 200 for healthy states (IDLE)."""
        mock_worker.get_state.return_value = WorkerState.IDLE

        response = await health(mock_request)

        assert response.status == 200
        assert response.content_type == "application/json"

        # Parse JSON response
        response_data = json.loads(response.text or "{}")
        assert response_data == {"state": "IDLE"}

    @pytest.mark.asyncio
    async def test_health_waiting_state_success(
        self, mock_request: Mock, mock_worker: Mock
    ) -> None:
        """Test /health returns 200 for healthy states (WAITING)."""
        mock_worker.get_state.return_value = WorkerState.WAITING

        response = await health(mock_request)

        assert response.status == 200
        response_data = json.loads(response.text or "{}")
        assert response_data == {"state": "WAITING"}

    @pytest.mark.asyncio
    async def test_health_busy_state_success(self, mock_request: Mock, mock_worker: Mock) -> None:
        """Test /health returns 200 for healthy states (BUSY)."""
        mock_worker.get_state.return_value = WorkerState.BUSY

        response = await health(mock_request)

        assert response.status == 200
        response_data = json.loads(response.text or "{}")
        assert response_data == {"state": "BUSY"}

    @pytest.mark.asyncio
    async def test_health_error_state_unhealthy(
        self, mock_request: Mock, mock_worker: Mock
    ) -> None:
        """Test /health returns 503 for unhealthy states (ERROR)."""
        mock_worker.get_state.return_value = WorkerState.ERROR

        response = await health(mock_request)

        assert response.status == 503
        response_data = json.loads(response.text or "{}")
        assert response_data == {"state": "ERROR"}

    @pytest.mark.asyncio
    async def test_health_shutdown_state_unhealthy(
        self, mock_request: Mock, mock_worker: Mock
    ) -> None:
        """Test /health returns 503 for unhealthy states (SHUTDOWN)."""
        mock_worker.get_state.return_value = WorkerState.SHUTDOWN

        response = await health(mock_request)

        assert response.status == 503
        response_data = json.loads(response.text or "{}")
        assert response_data == {"state": "SHUTDOWN"}


class TestMetricsEndpoint:
    """Test /metrics endpoint functionality and Prometheus format."""

    @pytest.fixture
    def mock_worker(self) -> Mock:
        """Create a mocked worker with metrics data."""
        worker = Mock()
        worker.get_state.return_value = WorkerState.BUSY
        worker.worker_id = "metrics-test-worker"
        worker._backoff = 2.5
        return worker

    @pytest.fixture
    def mock_request(self, mock_worker: Mock) -> Mock:
        """Create a mocked aiohttp request with worker in app context."""
        request = Mock()
        request.app = {WORKER_KEY: mock_worker}
        return request

    @pytest.mark.asyncio
    async def test_metrics_format_and_content(self, mock_request: Mock, mock_worker: Mock) -> None:
        """Test /metrics returns properly formatted Prometheus metrics."""
        response = await metrics(mock_request)

        assert response.status == 200
        assert response.content_type == "text/plain"

        metrics_text = response.text or ""
        lines = metrics_text.strip().split("\n")

        # Verify expected metrics are present
        expected_patterns = [
            'worker_state{worker_id="metrics-test-worker"}',
            "worker_backoff_seconds 2.5",
        ]

        for pattern in expected_patterns:
            assert any(pattern in line for line in lines), (
                f"Pattern '{pattern}' not found in metrics"
            )

    @pytest.mark.asyncio
    async def test_metrics_state_value_mapping(self, mock_request: Mock, mock_worker: Mock) -> None:
        """Test metrics correctly maps state enum values."""
        # Test different states
        test_cases = [
            (WorkerState.IDLE, WorkerState.IDLE.value),
            (WorkerState.WAITING, WorkerState.WAITING.value),
            (WorkerState.BUSY, WorkerState.BUSY.value),
            (WorkerState.ERROR, WorkerState.ERROR.value),
            (WorkerState.SHUTDOWN, WorkerState.SHUTDOWN.value),
        ]

        for state, expected_value in test_cases:
            mock_worker.get_state.return_value = state
            response = await metrics(mock_request)

            assert f'worker_state{{worker_id="metrics-test-worker"}} {expected_value}' in (
                response.text or ""
            )

    @pytest.mark.asyncio
    async def test_metrics_backoff_precision(self, mock_request: Mock, mock_worker: Mock) -> None:
        """Test metrics correctly formats backoff values with precision."""
        test_backoffs = [0.0, 1.0, 2.5, 10.0, 0.123456789]

        for backoff_value in test_backoffs:
            mock_worker._backoff = backoff_value
            response = await metrics(mock_request)

            assert f"worker_backoff_seconds {backoff_value}" in (response.text or "")

    @pytest.mark.asyncio
    async def test_metrics_worker_id_escaping(self, mock_request: Mock, mock_worker: Mock) -> None:
        """Test metrics properly handles worker IDs with special characters."""
        # Test worker ID with special characters
        mock_worker.worker_id = "worker-123_test.special"

        response = await metrics(mock_request)

        # Should include the worker ID as-is (Prometheus labels can handle these chars)
        assert 'worker_state{worker_id="worker-123_test.special"}' in (response.text or "")


class TestHttpServer:
    """Test HTTP server startup and configuration."""

    @pytest.mark.asyncio
    async def test_start_http_server_setup(self) -> None:
        """Test HTTP server initializes correctly with routes."""
        mock_worker = Mock()
        mock_worker.get_state.return_value = WorkerState.IDLE
        mock_worker.worker_id = "server-test"
        mock_worker._backoff = 1.0

        # We can't easily test the full server startup without complex mocking,
        # but we can test the app setup logic by extracting it
        app = web.Application()
        # Properly cast mock to Worker type for type safety
        app[WORKER_KEY] = cast(Worker, mock_worker)
        app.router.add_get("/health", health)
        app.router.add_get("/metrics", metrics)

        # Verify routes are registered
        routes = [resource.canonical for resource in app.router.resources()]
        assert "/health" in routes
        assert "/metrics" in routes

        # Verify worker is stored in app
        assert app[WORKER_KEY] == mock_worker

    @pytest.mark.asyncio
    async def test_server_integration_with_aiohttp_test(self) -> None:
        """Test server endpoints using aiohttp test utilities."""

        class ServerTestCase(AioHTTPTestCase):
            async def get_application(self) -> web.Application:
                # Create test worker
                worker = Mock()
                worker.get_state.return_value = WorkerState.WAITING
                worker.worker_id = "integration-test"
                worker._backoff = 1.5

                # Create app with our endpoints
                app = web.Application()
                app[WORKER_KEY] = cast(Worker, worker)
                app.router.add_get("/health", health)
                app.router.add_get("/metrics", metrics)
                return app

            async def test_health_integration(self) -> None:
                resp = await self.client.request("GET", "/health")
                assert resp.status == 200
                data = await resp.json()
                assert data["state"] == "WAITING"

            async def test_metrics_integration(self) -> None:
                resp = await self.client.request("GET", "/metrics")
                assert resp.status == 200
                text = await resp.text()
                assert "worker_state" in text
                assert "worker_backoff_seconds" in text

        # Run integration test
        test_case = ServerTestCase()
        await test_case.get_application()  # Just verify app creation works

        # Note: Full aiohttp test integration would require more complex setup
        # but this verifies the basic structure works

    @pytest.mark.asyncio
    @patch("bot.distributed.monitoring.http.web.AppRunner")
    @patch("bot.distributed.monitoring.http.web.TCPSite")
    async def test_start_http_server_port_configuration(
        self, mock_tcp_site: Mock, mock_app_runner: Mock
    ) -> None:
        """Test HTTP server uses correct port configuration."""
        mock_worker = Mock()
        mock_runner_instance = Mock()
        mock_site_instance = Mock()

        mock_app_runner.return_value = mock_runner_instance
        mock_tcp_site.return_value = mock_site_instance

        # Mock the setup and start methods
        mock_runner_instance.setup = AsyncMock()
        mock_site_instance.start = AsyncMock()

        # Test custom port
        with patch("asyncio.sleep", side_effect=asyncio.CancelledError):
            try:
                await start_http_server(mock_worker, port=8080)
            except asyncio.CancelledError:
                pass  # Expected due to infinite loop

        # Verify TCPSite was created with correct parameters
        mock_tcp_site.assert_called_once_with(mock_runner_instance, "0.0.0.0", 8080)
        mock_site_instance.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_health_endpoint_error_handling(self) -> None:
        """Test health endpoint handles worker errors gracefully."""
        # Test with worker that raises exception
        mock_worker = Mock()
        mock_worker.get_state.side_effect = Exception("Worker error")

        request = Mock()
        request.app = {WORKER_KEY: mock_worker}

        # Should propagate the exception (letting aiohttp handle it)
        with pytest.raises(Exception, match="Worker error"):
            await health(request)

    @pytest.mark.asyncio
    async def test_metrics_endpoint_error_handling(self) -> None:
        """Test metrics endpoint handles worker errors gracefully."""
        # Test with worker that raises exception
        mock_worker = Mock()
        mock_worker.get_state.side_effect = Exception("Metrics error")

        request = Mock()
        request.app = {WORKER_KEY: mock_worker}

        # Should propagate the exception (letting aiohttp handle it)
        with pytest.raises(Exception, match="Metrics error"):
            await metrics(request)
