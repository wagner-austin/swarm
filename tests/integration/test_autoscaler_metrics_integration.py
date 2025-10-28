import asyncio
import os
from typing import Optional

import pytest

from scripts.celery_autoscaler import CeleryAutoscaler
from tests.integration.utils import check_docker_services_running


@pytest.mark.integration
@pytest.mark.docker
@pytest.mark.asyncio
async def test_autoscaler_metrics_aggregate_depth_real_broker() -> None:
    services_ok, message = await check_docker_services_running()
    if not services_ok:
        pytest.skip(message)

    # Use the real Celery app configured via environment for tests
    from swarm.celery_app import app as celery_app

    # Use a test-specific queue that no workers consume from to prevent
    # tasks from being consumed before we can check the depth
    TEST_QUEUE = "test-browser-metrics"

    # Enqueue N tasks on the test queue
    N = 3
    for i in range(N):
        celery_app.send_task(
            "browser.goto",
            kwargs={"url": "https://example.com", "session_id": f"it-metrics-{i}"},
            queue=TEST_QUEUE,  # Explicit queue to avoid worker consumption
        )

    # Initialize autoscaler to verify it can read queue depth using the same method
    autoscaler = CeleryAutoscaler(orchestrator="docker-api")
    await autoscaler.setup()

    # Check queue depth directly using the autoscaler's queue_depth method
    # This tests that the autoscaler can correctly read from Redis with priority queues
    try:
        depth = await asyncio.to_thread(autoscaler.queue_depth, TEST_QUEUE)
    except Exception as e:
        pytest.fail(f"Failed to read queue depth: {e}")

    # Assert the queue depth matches what we sent
    assert depth >= N, f"expected depth >= {N}, got {depth}"

    # Cleanup: purge the test queue
    import redis.asyncio as redis

    password: str | None = os.getenv("REDIS_PASSWORD")
    host = os.getenv("REDIS_HOST", "localhost")
    port = int(os.getenv("REDIS_PORT", "6380"))
    url = f"redis://default:{password}@{host}:{port}/0" if password else f"redis://{host}:{port}/0"
    client = redis.from_url(url, decode_responses=True)
    try:
        # Delete all priority queue variants for the test queue
        for pri in range(10):
            key = f"{TEST_QUEUE}" if pri == 0 else f"{TEST_QUEUE}\x06\x16{pri}"
            await client.delete(key)
    finally:
        await client.aclose()
