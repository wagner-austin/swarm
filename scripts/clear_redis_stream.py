#!/usr/bin/env python3
import asyncio

import redis.asyncio as redis_asyncio

from swarm.infra import async_close_redis


async def clear_stream() -> None:
    r = redis_asyncio.from_url("redis://localhost:6379/0", decode_responses=True)

    # Delete the entire stream to clear all pending jobs
    result = await r.delete("jobs")
    print(f"Deleted jobs stream: {result}")

    # Recreate the stream and consumer group
    await r.xgroup_create("jobs", "all-workers", id="$", mkstream=True)
    print("Recreated empty stream and consumer group")

    await async_close_redis(r)


if __name__ == "__main__":
    asyncio.run(clear_stream())
