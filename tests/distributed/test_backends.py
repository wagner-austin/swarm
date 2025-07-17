"""
Tests for Distributed Scaling Backends
======================================

Tests the concrete scaling backend implementations to ensure they
properly implement the ScalingBackend protocol.
"""

import asyncio
from typing import Any, Dict, List, Type
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swarm.distributed.backends.docker_api import DockerApiBackend
from swarm.distributed.backends.fly_io import FlyIOBackend
from swarm.distributed.backends.kubernetes import KubernetesBackend
from swarm.distributed.services.scaling_service import ScalingBackend


class TestScalingBackendProtocol:
    """Test that all backends implement the ScalingBackend protocol."""

    @pytest.mark.parametrize(
        "backend_class,kwargs",
        [
            (DockerApiBackend, {}),
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


class TestDockerApiBackend:
    """Test DockerApiBackend functionality."""

    @pytest.fixture
    def backend(self) -> DockerApiBackend:
        """Create backend instance."""
        return DockerApiBackend(
            image="test-image:latest", network="test_network", project_name="test-project"
        )

    @pytest.mark.asyncio
    async def test_scale_to_creates_containers(self, backend: DockerApiBackend) -> None:
        """Test that scale_to creates correct number of containers."""
        with patch.object(backend, "get_current_count", return_value=1) as mock_count:
            with patch.object(
                backend, "_create_worker_container", return_value=True
            ) as mock_create:
                result = await backend.scale_to("browser", 3)

                assert result is True
                mock_count.assert_called_once_with("browser")
                # Should create 2 more containers (3 - 1 = 2)
                assert mock_create.call_count == 2

    @pytest.mark.asyncio
    async def test_scale_to_removes_containers(self, backend: DockerApiBackend) -> None:
        """Test that scale_to removes excess containers."""
        # Mock existing containers with proper attributes
        mock_container1 = MagicMock()
        mock_container1.name = "test_worker_3"
        mock_container2 = MagicMock()
        mock_container2.name = "test_worker_2"
        mock_containers = [mock_container1, mock_container2]

        with patch.object(backend, "get_current_count", return_value=3):
            with patch.object(backend, "_get_worker_containers", return_value=mock_containers):
                with patch.object(backend, "_remove_container") as mock_remove:
                    result = await backend.scale_to("browser", 1)

                    assert result is True
                    # Should remove 2 containers (3 - 1 = 2)
                    assert mock_remove.call_count == 2

    @pytest.mark.asyncio
    async def test_handles_scaling_failure(self, backend: DockerApiBackend) -> None:
        """Test handling of container creation failure."""
        with patch.object(backend, "get_current_count", return_value=0):
            with patch.object(backend, "_create_worker_container", return_value=False):
                result = await backend.scale_to("browser", 2)

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
            namespace="prod", deployment_prefix="swarm", kubeconfig="/path/to/kubeconfig"
        )

    @pytest.mark.asyncio
    async def test_scale_to_command_construction(self, backend: KubernetesBackend) -> None:
        """Test that scale_to constructs correct kubectl command."""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            # Mock successful execution
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(
                return_value=(b"deployment.apps/swarm-browser scaled", b"")
            )
            mock_exec.return_value = mock_proc

            result = await backend.scale_to("browser", 6)

            # Verify command construction
            assert result is True
            mock_exec.assert_called_once()
            cmd = mock_exec.call_args[0]

            assert "kubectl" in cmd
            assert "scale" in cmd
            assert "deployment/swarm-browser" in cmd
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
        assert backend._get_deployment_name("generic") == "swarm"
        assert backend._get_deployment_name("browser") == "swarm-browser"
        assert backend._get_deployment_name("gpu") == "swarm-gpu"
