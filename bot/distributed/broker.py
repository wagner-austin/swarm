import asyncio
import logging
import os
from typing import Any

import redis.asyncio as aioredis

from bot.distributed.model import Job

STREAM = os.getenv("JOB_STREAM", "jobs")

logger = logging.getLogger(__name__)


class Broker:
    """
    Distributed job broker using Redis streams. Ensures the stream and consumer group exist.
    """

    def __init__(self, redis_url: str) -> None:
        self._r = aioredis.from_url(redis_url, decode_responses=True)  # type: ignore[no-untyped-call]

    async def ensure_stream_and_group(self, group: str) -> None:
        """
        Ensure the Redis stream and consumer group exist. Idempotent and safe for concurrent startup.
        Logs all outcomes for observability.
        """
        try:
            await self._r.xgroup_create(STREAM, group, id="$", mkstream=True)
            logger.info("Created consumer group '%s' on stream '%s'.", group, STREAM)
        except Exception as exc:
            if "BUSYGROUP" in str(exc):
                logger.info("Consumer group '%s' already exists on stream '%s'.", group, STREAM)
            else:
                logger.exception(
                    "Error creating consumer group '%s' on stream '%s'.", group, STREAM
                )
                raise

    async def publish(self, job: Job) -> None:
        await self._r.xadd(STREAM, {"json": job.dumps()})

    async def publish_and_wait(self, job: Job, timeout: float = 30.0) -> dict[str, Any]:
        """
        Publish a job and wait for its result on the job_results Redis list.
        Returns the result dict, or raises TimeoutError/RuntimeError on failure.
        """
        import json

        logger.info(f"Publishing job {job.id} and waiting for result (timeout={timeout}s)")
        await self.publish(job)
        redis = self._r
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                logger.error(f"Timeout waiting for result of job {job.id}")
                raise TimeoutError(f"Timeout waiting for result of job {job.id}")
            # BLPOP returns [key, value] or None
            result = await redis.blpop("job_results", timeout=min(5, int(remaining)))
            if result is None:
                continue  # Timeout, but not expired yet
            try:
                data = json.loads(result[1])
                if not isinstance(data, dict):
                    logger.warning(f"Job result is not a dict: {data}")
                    continue
            except Exception as exc:
                logger.warning(f"Failed to decode job result: {exc}")
                continue
            if data.get("job_id") == job.id:
                logger.info(f"Received result for job {job.id}")
                return data
            else:
                # Not our job, push it back for others
                await redis.rpush("job_results", result[1])
                await asyncio.sleep(0.1)

    async def consume(self, group: str, consumer: str) -> Job:
        # ≤1 sec block; if nothing, function caller can loop/sleep
        max_retries = 2
        for attempt in range(max_retries):
            try:
                msgs = await self._r.xreadgroup(group, consumer, {STREAM: ">"}, count=1, block=1000)
                if msgs:
                    _, entries = msgs[0]
                    msg_id, fields = entries[0]
                    await self._r.xack(STREAM, group, msg_id)
                    return Job.loads(fields["json"])
                raise TimeoutError
            except Exception as exc:
                if "NOGROUP" in str(exc):
                    logger.warning(
                        "NOGROUP error for group '%s'. Re-creating and retrying...", group
                    )
                    await self.ensure_stream_and_group(group)
                    continue
                raise
        raise RuntimeError(
            f"[Broker] Failed to consume from group '{group}' on stream '{STREAM}' after {max_retries} attempts due to repeated NOGROUP errors."
        )
