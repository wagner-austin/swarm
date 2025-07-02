import asyncio
import os

import redis.asyncio as aioredis

from bot.distributed.model import Job

STREAM = os.getenv("JOB_STREAM", "jobs")


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
            print(f"[Broker] Created consumer group '{group}' on stream '{STREAM}'.")
        except Exception as exc:
            if "BUSYGROUP" in str(exc):
                print(f"[Broker] Consumer group '{group}' already exists on stream '{STREAM}'.")
            else:
                print(
                    f"[Broker] Error creating consumer group '{group}' on stream '{STREAM}': {exc}"
                )
                raise

    async def publish(self, job: Job) -> None:
        await self._r.xadd(STREAM, {"json": job.dumps()})

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
                    print(
                        f"[Broker] NOGROUP error encountered in consume. Attempting to create group '{group}' on stream '{STREAM}'."
                    )
                    await self.ensure_stream_and_group(group)
                    continue
                raise
        raise RuntimeError(
            f"[Broker] Failed to consume from group '{group}' on stream '{STREAM}' after {max_retries} attempts due to repeated NOGROUP errors."
        )
