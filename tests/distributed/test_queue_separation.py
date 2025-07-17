"""Test queue separation for different worker types."""

import pytest

from bot.distributed.broker import Broker
from bot.distributed.model import new_job


def test_job_routing_to_correct_queues() -> None:
    """Test that jobs are routed to their type-specific queues."""
    broker = Broker("redis://localhost")

    # Create jobs of different types
    browser_job = new_job("browser.screenshot", "https://example.com")
    tankpit_job = new_job("tankpit.spawn", "test-command")
    unknown_job = new_job("unknown.task", "data")

    # Test stream determination
    assert broker._get_stream_for_job_type(browser_job.type) == "browser:jobs"
    assert broker._get_stream_for_job_type(tankpit_job.type) == "tankpit:jobs"
    assert broker._get_stream_for_job_type(unknown_job.type) == "jobs"


@pytest.mark.asyncio
async def test_broker_publishes_to_correct_stream() -> None:
    """Test that broker publishes jobs to the correct streams."""
    from unittest.mock import AsyncMock, patch

    mock_redis = AsyncMock()

    with patch("bot.distributed.broker.redis_asyncio.from_url", return_value=mock_redis):
        broker = Broker("redis://localhost")

        # Test browser job
        browser_job = new_job("browser.screenshot", "https://example.com")
        await broker.publish(browser_job)
        mock_redis.xadd.assert_called_with("browser:jobs", {"json": browser_job.dumps()})

        # Test tankpit job
        tankpit_job = new_job("tankpit.spawn", "test-command")
        await broker.publish(tankpit_job)
        mock_redis.xadd.assert_called_with("tankpit:jobs", {"json": tankpit_job.dumps()})

        # Test unknown job goes to default
        unknown_job = new_job("custom.task", "data")
        await broker.publish(unknown_job)
        mock_redis.xadd.assert_called_with("jobs", {"json": unknown_job.dumps()})


@pytest.mark.asyncio
async def test_worker_consumes_from_correct_stream() -> None:
    """Test that workers consume from their type-specific streams."""
    from unittest.mock import AsyncMock, patch

    mock_redis = AsyncMock()

    with patch("bot.distributed.broker.redis_asyncio.from_url", return_value=mock_redis):
        broker = Broker("redis://localhost")

        # Mock xreadgroup to return a job
        mock_redis.xreadgroup.return_value = [
            (
                "browser:jobs",
                [
                    (
                        "123-0",
                        {
                            "json": '{"id": "1", "type": "browser.screenshot", "args": [], "kwargs": {}, "reply_to": "results", "created_ts": 0}'
                        },
                    )
                ],
            )
        ]

        # Browser worker should consume from browser:jobs
        job = await broker.consume("browser", "worker-1")
        mock_redis.xreadgroup.assert_called_with(
            "browser", "worker-1", {"browser:jobs": ">"}, count=1, block=1000
        )
        assert job.type == "browser.screenshot"

        # Tankpit worker should consume from tankpit:jobs
        mock_redis.xreadgroup.return_value = [
            (
                "tankpit:jobs",
                [
                    (
                        "124-0",
                        {
                            "json": '{"id": "2", "type": "tankpit.spawn", "args": [], "kwargs": {}, "reply_to": "results", "created_ts": 0}'
                        },
                    )
                ],
            )
        ]

        job = await broker.consume("tankpit", "worker-1")
        mock_redis.xreadgroup.assert_called_with(
            "tankpit", "worker-1", {"tankpit:jobs": ">"}, count=1, block=1000
        )
        assert job.type == "tankpit.spawn"
