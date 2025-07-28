"""
Typed wrappers for Redis stream commands and utilities.

These provide proper type annotations for Redis stream operations
that aren't fully typed in the redis-py library, as well as
compatibility helpers for different redis-py versions.
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


async def async_close_redis(client: Any) -> None:
    """
    Close an async redis-py client in a mypy-safe way.

    * redis-py 5.x: prefers `aclose()`
    * Older versions / stale stubs: only `close()`

    This helper exists because redis-py >= 5.0 offers aclose(), but the type stubs
    (and therefore mypy) haven't caught up yet. This provides a single, clean
    compatibility layer instead of scattering type: ignore comments everywhere.
    """
    if hasattr(client, "aclose"):  # new API
        await client.aclose()
    else:  # fallback / older stubs
        await client.close()
