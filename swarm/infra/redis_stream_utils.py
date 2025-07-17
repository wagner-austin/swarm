"""
Typed wrappers for Redis stream commands.

These provide proper type annotations for Redis stream operations
that aren't fully typed in the redis-py library.
"""

from typing import Any

from swarm.types import RedisBytes


async def xack(redis: RedisBytes, stream: str, group: str, *message_ids: str) -> int:
    """Acknowledge messages in a stream consumer group."""
    return int(await redis.xack(stream, group, *message_ids))


async def xpending(redis: RedisBytes, stream: str, group: str) -> list[Any]:
    """Get pending message information for a consumer group."""
    result = await redis.xpending(stream, group)
    if isinstance(result, list):
        return result
    return []


async def xinfo_groups(redis: RedisBytes, stream: str) -> list[dict[str, Any]]:
    """Get information about consumer groups for a stream."""
    groups = await redis.xinfo_groups(stream)
    return [dict(group) for group in groups] if groups else []
