import asyncio
import os

import aioredis

from bot.distributed.model import Job

STREAM = os.getenv("JOB_STREAM", "jobs")


class Broker:
    def __init__(self, redis_url: str) -> None:
        self._r = aioredis.from_url(redis_url, decode_responses=True)

    async def publish(self, job: Job) -> None:
        await self._r.xadd(STREAM, {"json": job.dumps()})

    async def consume(self, group: str, consumer: str) -> Job:
        # ≤1 sec block; if nothing, function caller can loop/sleep
        msgs = await self._r.xreadgroup(group, consumer, {STREAM: ">"}, count=1, block=1000)
        if msgs:
            _, entries = msgs[0]
            msg_id, fields = entries[0]
            await self._r.xack(STREAM, group, msg_id)
            return Job.loads(fields["json"])
        raise TimeoutError
