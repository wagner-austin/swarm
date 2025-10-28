"""
Runtime guard to prevent accidental FLUSH operations against non-test Redis.

Installs wrappers around redis.Redis/redis.asyncio.Redis flushdb/flushall that
only permit operations against localhost:6379 DB 15 or HAProxy test route 6380/0.
Tests that rely on flushdb should target localhost:6379/15 (see test files).
"""

from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable


@runtime_checkable
class _HasPool(Protocol):
    connection_pool: _PoolLike


class _PoolLike(Protocol):
    connection_kwargs: dict[str, object]


def _is_safe_connection(conn: _HasPool) -> bool:
    kwargs = conn.connection_pool.connection_kwargs
    host_obj = kwargs.get("host")
    port_obj = kwargs.get("port")
    db_obj = kwargs.get("db")
    host = str(host_obj) if host_obj is not None else ""
    port = int(port_obj) if isinstance(port_obj, int) else -1
    db = int(db_obj) if isinstance(db_obj, int) else -1

    # Allow strict local test database (6379/15)
    if host in {"localhost", "127.0.0.1"} and port == 6379 and db == 15:
        return True
    # Allow HAProxy test path (6380/0) when explicitly used for test control
    if host in {"haproxy-redis", "localhost"} and port == 6380 and db == 0:
        return True
    return False


def _wrap_flush(original: Callable[[object], object]) -> Callable[[object], object]:
    def _guard(self: object) -> object:
        if isinstance(self, _HasPool):
            if not _is_safe_connection(self):
                raise RuntimeError(
                    "Refusing to FLUSH non-test Redis (requires localhost:6379 db=15)"
                )
        return original(self)

    return _guard


def install() -> None:
    try:
        import redis  # type: ignore[import-not-found]

        if hasattr(redis, "Redis"):
            if hasattr(redis.Redis, "flushdb"):
                redis.Redis.flushdb = _wrap_flush(redis.Redis.flushdb)  # type: ignore[assignment]
            if hasattr(redis.Redis, "flushall"):
                redis.Redis.flushall = _wrap_flush(redis.Redis.flushall)  # type: ignore[assignment]
    except Exception:
        # Best-effort; guard not installed
        pass

    try:
        from redis import asyncio as redis_asyncio  # type: ignore[import-not-found]

        if hasattr(redis_asyncio, "Redis"):
            if hasattr(redis_asyncio.Redis, "flushdb"):
                redis_asyncio.Redis.flushdb = _wrap_flush(  # type: ignore[assignment]
                    redis_asyncio.Redis.flushdb
                )
            if hasattr(redis_asyncio.Redis, "flushall"):
                redis_asyncio.Redis.flushall = _wrap_flush(  # type: ignore[assignment]
                    redis_asyncio.Redis.flushall
                )
    except Exception:
        # Optional
        pass


__all__ = ["install"]
