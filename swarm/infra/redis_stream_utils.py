"""
Typed wrappers for Redis stream commands and utilities.

These provide proper type annotations for Redis stream operations
that aren't fully typed in the redis-py library, as well as
compatibility helpers for different redis-py versions.
"""

from typing import (
    Awaitable,
    NotRequired,
    Protocol,
    TypedDict,
    TypeGuard,
    overload,
    runtime_checkable,
)

from swarm.types import RedisBytes


async def xack(redis: RedisBytes, stream: str, group: str, *message_ids: str) -> int:
    """Acknowledge messages in a stream consumer group."""
    return int(await redis.xack(stream, group, *message_ids))


async def xpending(redis: RedisBytes, stream: str, group: str) -> list[object]:
    """Get pending message information for a consumer group."""
    result = await redis.xpending(stream, group)
    if isinstance(result, list):
        return result
    return []


# Use functional TypedDict to allow hyphenated keys from Redis response
StreamGroupInfo = TypedDict(
    "StreamGroupInfo",
    {
        "name": str | bytes,
        "consumers": int,
        "pending": int,
        "last-delivered-id": str | bytes,
        "entries_read": int,
        "lag": int,
    },
    total=False,
)


async def xinfo_groups(redis: RedisBytes, stream: str) -> list[StreamGroupInfo]:
    """Get information about consumer groups for a stream."""
    groups = await redis.xinfo_groups(stream)
    result: list[StreamGroupInfo] = []
    for g in groups or []:
        d = dict(g)
        info: StreamGroupInfo = {
            "name": d.get("name", b""),
            "consumers": int(d.get("consumers", 0) or 0),
            "pending": int(d.get("pending", 0) or 0),
            "last-delivered-id": d.get("last-delivered-id", b""),
            "entries_read": int(d.get("entries_read", 0) or 0),
            "lag": int(d.get("lag", 0) or 0),
        }
        result.append(info)
    return result


@runtime_checkable
class HasAClose(Protocol):
    async def aclose(self) -> None: ...


# Backward-compatible alias (previously imported by redis_protocols)
_HasAClose = HasAClose


@runtime_checkable
class HasClose(Protocol):
    # May be sync or async; narrowed at runtime with a TypeGuard
    def close(self) -> object: ...


Closeable = HasAClose | HasClose


@overload
async def async_close_redis(client: HasAClose) -> None: ...


@overload
async def async_close_redis(client: HasClose) -> None: ...


async def async_close_redis(client: Closeable) -> None:
    """Close an async Redis client with strict typing and no casts.

    Supported variants (checked in order):
    - client.aclose() for clients providing an explicit async aclose()
    - client.close() for clients with either async or sync close() (narrowed at runtime)
    """
    if isinstance(client, HasAClose):
        await client.aclose()
        return

    if isinstance(client, HasClose):
        result = client.close()
        if _is_awaitable_none(result):
            await result
        return

    # This should be unreachable due to the union type; keep explicit error for safety
    raise AttributeError(f"Client {type(client).__name__} has neither aclose() nor close()")


def _is_awaitable_none(value: object) -> TypeGuard[Awaitable[None]]:
    """TypeGuard to detect awaitable values that resolve to None."""
    return hasattr(value, "__await__")
