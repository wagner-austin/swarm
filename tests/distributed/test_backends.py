"""
Tests for Distributed Scaling Backends
======================================

Tests the concrete scaling backend implementations to ensure they
properly implement the ScalingBackend protocol.
"""

import asyncio
from typing import Any, Dict, List, Type
from unittest.mock import AsyncMock, patch

import pytest

from bot.distributed.backends.docker_compose import DockerComposeBackend
from bot.distributed.backends.fly_io import FlyIOBackend
from bot.distributed.backends.kubernetes import KubernetesBackend
from bot.distributed.services.scaling_service import ScalingBackend


class TestScalingBackendProtocol:
    """Test that all backends implement the ScalingBackend protocol."""

    @pytest.mark.parametrize(
        "backend_class,kwargs",
        [
            (DockerComposeBackend, {}),
            (FlyIOBackend, {"app_name": "test-app"}),
            (KubernetesBackend, {}),
        ],
    )
    def test_backend_implements_protocol(
        self, backend_class: type[ScalingBackend], kwargs: dict[str, Any]
    ) -> None:
        """Test that backend classes implement the protocol."""
        backend = backend_class(**kwargs)

        # Verify it's an instance of the protocol
        assert isinstance(backend, ScalingBackend)

        # Verify required methods exist and are coroutines
        assert hasattr(backend, "scale_to")
        assert hasattr(backend, "get_current_count")
        assert asyncio.iscoroutinefunction(backend.scale_to)
        assert asyncio.iscoroutinefunction(backend.get_current_count)


class TestDockerComposeBackend:
    """Test DockerComposeBackend command construction."""

    @pytest.fixture
    def backend(self) -> DockerComposeBackend:
        """Create backend instance."""
        return DockerComposeBackend(compose_file="test-compose.yml", project_name="test-project")

    @pytest.mark.asyncio
    async def test_scale_to_command_construction(self, backend: DockerComposeBackend) -> None:
        """Test that scale_to constructs correct docker-compose command."""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            # Mock successful execution
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(b"", b""))
            mock_exec.return_value = mock_proc

            result = await backend.scale_to("browser", 3)

            # Verify command construction
            assert result is True
            mock_exec.assert_called_once()
            cmd = mock_exec.call_args[0]

            # Check command components
            assert "docker-compose" in cmd
            assert "-f" in cmd
            assert "test-compose.yml" in cmd
            assert "-p" in cmd
            assert "test-project" in cmd
            assert "up" in cmd
            assert "-d" in cmd
            assert "--scale" in cmd
            assert "worker=3" in cmd
            assert "--no-recreate" in cmd

    @pytest.mark.asyncio
    async def test_get_current_count_command_construction(
        self, backend: DockerComposeBackend
    ) -> None:
        """Test that get_current_count constructs correct ps command."""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            # Mock ps command output
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(b"container1\ncontainer2\n", b""))
            mock_exec.return_value = mock_proc

            count = await backend.get_current_count("browser")

            # Verify result and command
            assert count == 2
            mock_exec.assert_called_once()
            cmd = mock_exec.call_args[0]

            assert "docker-compose" in cmd
            assert "-f" in cmd
            assert "test-compose.yml" in cmd
            assert "-p" in cmd
            assert "test-project" in cmd
            assert "ps" in cmd
            assert "-q" in cmd
            assert "worker" in cmd

    @pytest.mark.asyncio
    async def test_handles_scaling_failure(self, backend: DockerComposeBackend) -> None:
        """Test handling of scaling command failure."""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            # Mock failed execution
            mock_proc = AsyncMock()
            mock_proc.returncode = 1
            mock_proc.communicate = AsyncMock(return_value=(b"", b"Error: service not found"))
            mock_exec.return_value = mock_proc

            result = await backend.scale_to("browser", 5)

            assert result is False


class TestFlyIOBackend:
    """Test FlyIOBackend command construction."""

    @pytest.fixture
    def backend(self) -> FlyIOBackend:
        """Create backend instance."""
        return FlyIOBackend(app_name="test-app", process_group="worker", region="iad")

    def test_requires_app_name(self) -> None:
        """Test that app name is required."""
        with pytest.raises(ValueError, match="app name must be provided"):
            FlyIOBackend()

    @pytest.mark.asyncio
    async def test_scale_to_command_construction(self, backend: FlyIOBackend) -> None:
        """Test that scale_to constructs correct fly command."""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            # Mock successful execution
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(b"Scaled", b""))
            mock_exec.return_value = mock_proc

            result = await backend.scale_to("browser", 4)

            # Verify command construction
            assert result is True
            mock_exec.assert_called_once()
            cmd = mock_exec.call_args[0]

            assert "fly" in cmd
            assert "scale" in cmd
            assert "count" in cmd
            assert "worker-browser=4" in cmd
            assert "--app" in cmd
            assert "test-app" in cmd
            assert "--region" in cmd
            assert "iad" in cmd

    @pytest.mark.asyncio
    async def test_get_current_count_parses_json(self, backend: FlyIOBackend) -> None:
        """Test parsing of fly status JSON output."""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            # Mock status command with JSON output
            status_json = """
            {
                "Machines": [
                    {"process_group": "worker-browser", "state": "started"},
                    {"process_group": "worker-browser", "state": "running"},
                    {"process_group": "worker-browser", "state": "stopped"},
                    {"process_group": "web", "state": "started"}
                ]
            }
            """
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(status_json.encode(), b""))
            mock_exec.return_value = mock_proc

            count = await backend.get_current_count("browser")

            # Should only count started/running machines
            assert count == 2

    def test_process_name_mapping(self, backend: FlyIOBackend) -> None:
        """Test worker type to process name mapping."""
        assert backend._get_process_name("generic") == "worker"
        assert backend._get_process_name("browser") == "worker-browser"
        assert backend._get_process_name("gpu") == "worker-gpu"


class TestKubernetesBackend:
    """Test KubernetesBackend command construction."""

    @pytest.fixture
    def backend(self) -> KubernetesBackend:
        """Create backend instance."""
        return KubernetesBackend(
            namespace="prod", deployment_prefix="discord-bot", kubeconfig="/path/to/kubeconfig"
        )

    @pytest.mark.asyncio
    async def test_scale_to_command_construction(self, backend: KubernetesBackend) -> None:
        """Test that scale_to constructs correct kubectl command."""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            # Mock successful execution
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(
                return_value=(b"deployment.apps/discord-bot-browser scaled", b"")
            )
            mock_exec.return_value = mock_proc

            result = await backend.scale_to("browser", 6)

            # Verify command construction
            assert result is True
            mock_exec.assert_called_once()
            cmd = mock_exec.call_args[0]

            assert "kubectl" in cmd
            assert "scale" in cmd
            assert "deployment/discord-bot-browser" in cmd
            assert "--replicas=6" in cmd
            assert "--namespace=prod" in cmd
            assert "--kubeconfig" in cmd
            assert "/path/to/kubeconfig" in cmd

    @pytest.mark.asyncio
    async def test_get_current_count_parses_json(self, backend: KubernetesBackend) -> None:
        """Test parsing of kubectl deployment JSON output."""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            # Mock get deployment command with JSON output
            deployment_json = """
            {
                "status": {
                    "replicas": 5,
                    "readyReplicas": 3,
                    "unavailableReplicas": 2
                }
            }
            """
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(deployment_json.encode(), b""))
            mock_exec.return_value = mock_proc

            count = await backend.get_current_count("browser")

            # Should return ready replicas
            assert count == 3

    @pytest.mark.asyncio
    async def test_handles_missing_ready_replicas(self, backend: KubernetesBackend) -> None:
        """Test handling deployment with no ready replicas."""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            # Deployment with no ready replicas field
            deployment_json = """
            {
                "status": {
                    "replicas": 3
                }
            }
            """
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(deployment_json.encode(), b""))
            mock_exec.return_value = mock_proc

            count = await backend.get_current_count("browser")

            # Should return 0 when no ready replicas
            assert count == 0

    def test_deployment_name_mapping(self, backend: KubernetesBackend) -> None:
        """Test worker type to deployment name mapping."""
        assert backend._get_deployment_name("generic") == "discord-bot"
        assert backend._get_deployment_name("browser") == "discord-bot-browser"
        assert backend._get_deployment_name("gpu") == "discord-bot-gpu"
