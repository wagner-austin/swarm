import asyncio
import logging
import os
from typing import Any

import redis.asyncio as redis_asyncio

from bot.distributed.model import Job

logger = logging.getLogger(__name__)


class Broker:
    """
    Distributed job broker using Redis streams. Routes jobs to type-specific streams.
    """

    def __init__(self, redis_url: str) -> None:
        self._r = redis_asyncio.from_url(redis_url, decode_responses=True)  # type: ignore[no-untyped-call]
        # Default stream for backward compatibility
        self._default_stream = os.getenv("JOB_STREAM", "jobs")

    def _get_stream_for_job_type(self, job_type: str) -> str:
        """
        Determine the stream name based on job type.

        Examples:
            "browser.screenshot" -> "browser:jobs"
            "tankpit.spawn" -> "tankpit:jobs"
            "unknown.task" -> "jobs" (default)
        """
        if "." in job_type:
            prefix = job_type.split(".", 1)[0]
            # Map known prefixes to their streams
            if prefix in ["browser", "tankpit"]:
                return f"{prefix}:jobs"
        return self._default_stream

    async def ensure_stream_and_group(self, stream: str, group: str) -> None:
        """
        Ensure the Redis stream and consumer group exist. Idempotent and safe for concurrent startup.
        Logs all outcomes for observability.

        Args:
            stream: The stream name (e.g., "browser:jobs", "tankpit:jobs")
            group: The consumer group name
        """
        try:
            await self._r.xgroup_create(stream, group, id="$", mkstream=True)
            logger.info("Created consumer group '%s' on stream '%s'.", group, stream)
        except Exception as exc:
            if "BUSYGROUP" in str(exc):
                logger.info("Consumer group '%s' already exists on stream '%s'.", group, stream)
            else:
                logger.exception(
                    "Error creating consumer group '%s' on stream '%s'.", group, stream
                )
                raise

    async def publish(self, job: Job) -> None:
        """Publish a job to the appropriate stream based on its type."""
        stream = self._get_stream_for_job_type(job.type)
        await self._r.xadd(stream, {"json": job.dumps()})

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
                logger.error(f"Failed to decode job result (data corruption): {exc}")
                continue
            if data.get("job_id") == job.id:
                logger.info(f"Received result for job {job.id}")
                return data
            else:
                # Not our job, push it back for others
                await redis.rpush("job_results", result[1])
                await asyncio.sleep(0.1)

    async def consume(self, group: str, consumer: str, stream: str | None = None) -> Job:
        """
        Consume a job from the specified stream.

        Args:
            group: Consumer group name (e.g., "browser", "tankpit")
            consumer: Consumer name within the group
            stream: Stream to consume from. If None, uses the group name to determine stream.
        """
        # Determine stream based on group name if not specified
        if stream is None:
            # Group name typically matches worker type (e.g., "browser", "tankpit")
            if group in ["browser", "tankpit"]:
                stream = f"{group}:jobs"
            else:
                stream = self._default_stream

        # ≤1 sec block; if nothing, function caller can loop/sleep
        max_retries = 2
        for attempt in range(max_retries):
            try:
                msgs = await self._r.xreadgroup(group, consumer, {stream: ">"}, count=1, block=1000)
                if msgs:
                    stream_name, entries = msgs[0]
                    msg_id, fields = entries[0]
                    await self._r.xack(stream_name, group, msg_id)
                    return Job.loads(fields["json"])
                raise TimeoutError
            except Exception as exc:
                if "NOGROUP" in str(exc):
                    logger.warning(
                        "NOGROUP error for group '%s' on stream '%s'. Re-creating and retrying...",
                        group,
                        stream,
                    )
                    await self.ensure_stream_and_group(stream, group)
                    continue
                raise
        raise RuntimeError(
            f"[Broker] Failed to consume from group '{group}' on stream '{stream}' after {max_retries} attempts due to repeated NOGROUP errors."
        )
