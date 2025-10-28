from unittest.mock import AsyncMock

import pytest
from prometheus_client import generate_latest

from scripts.celery_autoscaler import CeleryAutoscaler


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
                "browser": type(
                    "W",
                    (),
                    {
                        "enabled": True,
                        "job_queue": "browser:jobs",
                        "scaling": type(
                            "S",
                            (),
                            {
                                "min_workers": 1,
                                "max_workers": 5,
                                "scale_up_threshold": 1,
                                "scale_down_threshold": 0,
                            },
                        )(),
                    },
                )()
            }
        },
    )()

    # Backend mock: current count 0, scale_to returns True
    autoscaler.backend = AsyncMock()
    autoscaler.backend.get_current_count.return_value = 0
    autoscaler.backend.scale_to.return_value = True

    # No real broker needed; overridden queue_depth/discover_queues provide values
    # But get_queue_stats checks _conn presence; provide a dummy conn
    class _DummyQ:
        def qsize(self) -> int:
            return 3

        def close(self) -> None:
            return None

    class _DummyConn:
        def SimpleQueue(self, name: str) -> _DummyQ:  # noqa: N802
            return _DummyQ()

        def close(self) -> None:
            return None

    autoscaler._conn = _DummyConn()

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
