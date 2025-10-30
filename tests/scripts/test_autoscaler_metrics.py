import pytest
from prometheus_client import generate_latest

from scripts.celery_autoscaler import CeleryAutoscaler
from swarm.distributed.core.config import ScalingConfig, WorkerTypeConfig
from swarm.distributed.protocols import ScalingBackend


@pytest.mark.asyncio
async def test_autoscaler_metrics_updated_on_scale() -> None:
    class DummyAutoscaler(CeleryAutoscaler):
        def discover_queues(self, base_prefix: str) -> set[str]:
            return {base_prefix}

        def queue_depth(self, name: str) -> int:
            return 3

    autoscaler = DummyAutoscaler(orchestrator="docker-api")
    autoscaler.config = type(
        "Cfg",
        (),
        {
            "worker_types": {
                "browser": WorkerTypeConfig(
                    name="browser",
                    job_queue="browser:jobs",
                    scaling=ScalingConfig(
                        min_workers=1,
                        max_workers=5,
                        scale_up_threshold=1,
                        scale_down_threshold=0,
                    ),
                    enabled=True,
                )
            }
        },
    )()

    class _FakeBackend(ScalingBackend):
        def __init__(self) -> None:
            self._current = 0
            self.last_scaled_to: int | None = None

        async def get_current_count(self, worker_type: str) -> int:  # noqa: ARG002
            return int(self._current)

        async def scale_to(self, worker_type: str, target_count: int) -> bool:  # noqa: ARG002
            self.last_scaled_to = int(target_count)
            self._current = int(target_count)
            return True

    autoscaler.backend = _FakeBackend()

    # No real broker needed; overridden queue_depth/discover_queues provide values
    # But get_queue_stats checks _conn presence; provide a dummy conn
    # Provide a non-None broker connection sentinel
    autoscaler._conn = object()

    await autoscaler.check_and_scale()

    metrics = generate_latest().decode()

    # Verify queue depth metric is set (allow either integer or float rendering)
    depth_line_prefix = 'autoscaler_queue_depth{queue="browser"} '
    lines = [ln for ln in metrics.splitlines() if ln.startswith(depth_line_prefix)]
    assert lines, f"autoscaler_queue_depth for browser missing in metrics:\n{metrics}"
    val = lines[0][len(depth_line_prefix) :].strip()
    assert val in ("3", "3.0"), f"unexpected depth value: {val}"

    # Verify decision/target metrics are set (scale up from 0 to 1)
    assert 'autoscaler_decision{worker_type="browser"} 1.0' in metrics
    assert 'autoscaler_target{worker_type="browser"} 1.0' in metrics
