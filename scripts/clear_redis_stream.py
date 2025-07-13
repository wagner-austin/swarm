#!/usr/bin/env python3
import asyncio

import redis.asyncio as aioredis


async def clear_stream() -> None:
    r = aioredis.from_url("redis://localhost:6379/0", decode_responses=True)  # type: ignore[no-untyped-call]

    # Delete the entire stream to clear all pending jobs
    result = await r.delete("jobs")
    print(f"Deleted jobs stream: {result}")

    # Recreate the stream and consumer group
    await r.xgroup_create("jobs", "all-workers", id="$", mkstream=True)
    print("Recreated empty stream and consumer group")

    await r.aclose()


if __name__ == "__main__":
    asyncio.run(clear_stream())
