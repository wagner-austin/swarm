from __future__ import annotations

from typing import AsyncIterator, Iterator, Mapping, Protocol, runtime_checkable

from swarm.types import RedisStr, RedisSyncStr  # must precede runtime code to satisfy ruff E402

from .redis_stream_utils import (
    _HasAClose,
    async_close_redis,
)  # must precede runtime code to satisfy ruff E402


@runtime_checkable
class RedisAsyncProtocol(Protocol):
    """Complete async Redis protocol used across modules.

    Includes lifecycle methods to ensure safe shutdown and compatibility
    with redis-py versions and stubs.
    """

    # Hash operations
    async def hset(
        self,
        name: str,
        key: str | None = None,
        value: str | None = None,
        *,
        mapping: dict[str, str] | None = None,
    ) -> int: ...  # number of fields added

    async def hget(self, name: str, key: str) -> str | None: ...

    # List operations
    async def rpush(self, key: str, *values: str) -> int: ...  # new length
    async def ltrim(self, key: str, start: int, stop: int) -> bool: ...
    async def lrange(self, key: str, start: int, stop: int) -> list[str]: ...

    # Key operations
    async def delete(self, *names: str) -> int: ...
    async def keys(self, pattern: str) -> list[str]: ...
    def scan_iter(self, *, match: str) -> AsyncIterator[str]: ...

    # TTL operations
    async def ttl(self, name: str) -> int: ...
    async def expire(self, name: str, time: int) -> bool: ...

    # Set operations
    async def srem(self, name: str, *values: str) -> int: ...

    # Lifecycle
    async def close(self) -> None: ...
    async def aclose(self) -> None: ...


@runtime_checkable
class RedisSyncProtocol(Protocol):
    """Complete sync Redis protocol used across modules."""

    # Hash operations
    def hset(
        self,
        name: str,
        key: str | None = None,
        value: str | None = None,
        *,
        mapping: dict[str, str] | None = None,
    ) -> int: ...

    def hget(self, name: str, key: str) -> str | None: ...
    def hgetall(self, name: str) -> dict[str, str]: ...

    # String operations
    def setex(self, name: str, time: int, value: str) -> bool: ...

    # Key operations
    def delete(self, *names: str) -> int: ...
    def keys(self, pattern: str) -> list[str]: ...
    def exists(self, name: str) -> int: ...

    # Set operations
    def smembers(self, name: str) -> set[str]: ...
    def sadd(self, name: str, *values: str) -> int: ...
    def srem(self, name: str, *values: str) -> int: ...
    def scard(self, name: str) -> int: ...

    # TTL operations
    def expire(self, name: str, ttl: int) -> bool: ...

    # Pipeline
    def pipeline(self) -> _PipelineProtocol: ...

    # Lifecycle (not currently used by callers but standardized here)
    def close(self) -> None: ...


class _PipelineProtocol(Protocol):
    def hset(
        self,
        name: str,
        key: str | None = None,
        value: str | None = None,
        *,
        mapping: dict[str, str] | None = None,
    ) -> _PipelineProtocol: ...
    def expire(self, name: str, ttl: int) -> _PipelineProtocol: ...
    def delete(self, *names: str) -> _PipelineProtocol: ...
    def execute(self) -> list[object]: ...
    def __enter__(self) -> _PipelineProtocol: ...
    def __exit__(self, exc_type: object | None, exc: object | None, tb: object | None) -> None: ...


_Scalar = str | bytes | int | float


@runtime_checkable
class _AioRedisLike(Protocol):
    async def hset(
        self,
        name: str,
        key: str | None = None,
        value: str | None = None,
        *,
        mapping: Mapping[str | bytes, _Scalar] | None = None,
    ) -> int | bool: ...

    async def hget(self, name: str, key: str) -> _Scalar | None: ...
    async def rpush(self, key: str, *values: str) -> int | bool: ...
    async def ltrim(self, key: str, start: int, stop: int) -> int | bool: ...
    async def lrange(self, key: str, start: int, stop: int) -> list[_Scalar]: ...
    async def delete(self, *names: str) -> int | bool: ...
    async def keys(self, pattern: str) -> list[_Scalar]: ...
    def scan_iter(self, *, match: str) -> AsyncIterator[_Scalar] | Iterator[_Scalar]: ...
    async def ttl(self, name: str) -> int | float: ...
    async def expire(self, name: str, time: int) -> bool | int: ...
    async def srem(self, name: str, *values: str) -> int | bool: ...
    async def aclose(self) -> None: ...


@runtime_checkable
class _SyncRedisLike(Protocol):
    def hset(
        self,
        name: str,
        key: str | None = None,
        value: str | None = None,
        *,
        mapping: Mapping[str | bytes, _Scalar] | None = None,
    ) -> int | bool: ...

    def hget(self, name: str, key: str) -> _Scalar | None: ...
    def hgetall(self, name: str) -> Mapping[_Scalar, _Scalar]: ...
    def setex(self, name: str, time: int, value: str) -> bool | int: ...
    def delete(self, *names: str) -> int: ...
    def keys(self, pattern: str) -> list[_Scalar]: ...
    def exists(self, name: str) -> int | bool: ...
    def smembers(self, name: str) -> set[_Scalar]: ...
    def sadd(self, name: str, *values: str) -> int | bool: ...
    def srem(self, name: str, *values: str) -> int | bool: ...
    def scard(self, name: str) -> int: ...
    def expire(self, name: str, time: int) -> bool | int: ...
    def pipeline(self) -> object: ...


def wrap_redis_async(client: object) -> RedisAsyncProtocol:
    """Type-safe wrapper for redis.asyncio.Redis clients.

    Ensures Protocol compliance, normalizes return types to `str` where
    necessary, adapts `scan_iter` to an async iterator, and provides
    lifecycle methods that work across redis-py versions.
    """

    class _RedisAsyncWrapper:
        def __init__(self, inner: object) -> None:
            assert isinstance(inner, _AioRedisLike)
            self._c: _AioRedisLike = inner

        # Hash operations
        async def hset(
            self,
            name: str,
            key: str | None = None,
            value: str | None = None,
            *,
            mapping: dict[str, str] | None = None,
        ) -> int:
            if mapping is not None:
                total = 0
                for k, v in mapping.items():
                    total += int(await self._c.hset(name, k, v))
                return total
            assert key is not None and value is not None
            return int(await self._c.hset(name, key, value))

        async def hget(self, name: str, key: str) -> str | None:
            val = await self._c.hget(name, key)
            if val is None:
                return None
            return val if isinstance(val, str) else str(val)

        # List operations
        async def rpush(self, key: str, *values: str) -> int:
            return int(await self._c.rpush(key, *values))

        async def ltrim(self, key: str, start: int, stop: int) -> bool:
            res = await self._c.ltrim(key, start, stop)
            return bool(res) if isinstance(res, int | bool) else True

        async def lrange(self, key: str, start: int, stop: int) -> list[str]:
            data = await self._c.lrange(key, start, stop)
            return [d if isinstance(d, str) else str(d) for d in data or []]

        # Key operations
        async def delete(self, *names: str) -> int:
            return int(await self._c.delete(*names))

        async def keys(self, pattern: str) -> list[str]:
            data = await self._c.keys(pattern)
            return [d if isinstance(d, str) else str(d) for d in data or []]

        def scan_iter(self, *, match: str) -> AsyncIterator[str]:
            async def _aiter() -> AsyncIterator[str]:
                it = self._c.scan_iter(match=match)
                if hasattr(it, "__aiter__"):
                    async for k in it:  # async iterator path
                        yield k if isinstance(k, str) else str(k)
                else:
                    for k in it:  # sync iterator path
                        yield k if isinstance(k, str) else str(k)

            return _aiter()

        # TTL operations
        async def ttl(self, name: str) -> int:
            return int(await self._c.ttl(name))

        async def expire(self, name: str, time: int) -> bool:
            res = await self._c.expire(name, time)
            return bool(res)

        # Set operations
        async def srem(self, name: str, *values: str) -> int:
            return int(await self._c.srem(name, *values))

        # Lifecycle
        async def close(self) -> None:
            await async_close_redis(self._c)

        async def aclose(self) -> None:
            await self.close()

    return _RedisAsyncWrapper(client)


def wrap_redis_sync(client: object) -> RedisSyncProtocol:
    """Minimal sync wrapper to satisfy the central Protocol.

    Currently delegates directly; kept for parity with async wrapper and
    future-proofing around lifecycle or compatibility shims.
    """

    class _RedisSyncWrapper:
        def __init__(self, inner: object) -> None:
            assert isinstance(inner, _SyncRedisLike)
            self._c: _SyncRedisLike = inner

        # Hash
        def hset(
            self,
            name: str,
            key: str | None = None,
            value: str | None = None,
            *,
            mapping: dict[str, str] | None = None,
        ) -> int:
            if mapping is not None:
                total = 0
                for k, v in mapping.items():
                    total += int(self._c.hset(name, k, v))
                return total
            assert key is not None and value is not None
            return int(self._c.hset(name, key, value))

        def hget(self, name: str, key: str) -> str | None:
            val = self._c.hget(name, key)
            if val is None:
                return None
            return val if isinstance(val, str) else str(val)

        def hgetall(self, name: str) -> dict[str, str]:
            d = self._c.hgetall(name)
            return {
                (k if isinstance(k, str) else str(k)): (v if isinstance(v, str) else str(v))
                for k, v in (d or {}).items()
            }

        # Strings / keys / sets / ttl
        def setex(self, name: str, time: int, value: str) -> bool:
            res = self._c.setex(name, time, value)
            return bool(res)

        def delete(self, *names: str) -> int:
            return int(self._c.delete(*names))

        def keys(self, pattern: str) -> list[str]:
            data = self._c.keys(pattern)
            return [d if isinstance(d, str) else str(d) for d in data or []]

        def exists(self, name: str) -> int:
            return int(self._c.exists(name))

        def smembers(self, name: str) -> set[str]:
            s = self._c.smembers(name)
            return {x if isinstance(x, str) else str(x) for x in s or set()}

        def sadd(self, name: str, *values: str) -> int:
            return int(self._c.sadd(name, *values))

        def srem(self, name: str, *values: str) -> int:
            return int(self._c.srem(name, *values))

        def scard(self, name: str) -> int:
            return int(self._c.scard(name))

        def expire(self, name: str, ttl: int) -> bool:
            res = self._c.expire(name, ttl)
            return bool(res)

        def pipeline(self) -> _PipelineProtocol:
            inner_obj = self._c.pipeline()

            @runtime_checkable
            class _PipelineLike(Protocol):
                def hset(
                    self,
                    name: str,
                    key: str | None = None,
                    value: str | None = None,
                    *,
                    mapping: dict[str, str] | None = None,
                ) -> object: ...

                def expire(self, name: str, ttl: int) -> object: ...
                def delete(self, *names: str) -> object: ...
                def execute(self) -> object: ...
                def __enter__(self) -> _PipelineLike: ...
                def __exit__(
                    self, exc_type: object | None, exc: object | None, tb: object | None
                ) -> None: ...

            assert isinstance(inner_obj, _PipelineLike)
            p: _PipelineLike = inner_obj

            class _PipelineAdapter:
                def __init__(self, p: _PipelineLike) -> None:
                    self._p = p

                def hset(
                    self,
                    name: str,
                    key: str | None = None,
                    value: str | None = None,
                    *,
                    mapping: dict[str, str] | None = None,
                ) -> _PipelineProtocol:
                    if mapping is not None:
                        self._p.hset(name, mapping=mapping)
                    else:
                        assert key is not None and value is not None
                        self._p.hset(name, key, value)
                    return self

                def expire(self, name: str, ttl: int) -> _PipelineProtocol:
                    self._p.expire(name, ttl)
                    return self

                def delete(self, *names: str) -> _PipelineProtocol:
                    self._p.delete(*names)
                    return self

                def execute(self) -> list[object]:
                    res = self._p.execute()
                    return list(res) if isinstance(res, list) else [res]

                def __enter__(self) -> _PipelineProtocol:
                    self._p.__enter__()
                    return self

                def __exit__(
                    self, exc_type: object | None, exc: object | None, tb: object | None
                ) -> None:
                    self._p.__exit__(exc_type, exc, tb)

            return _PipelineAdapter(p)

        def close(self) -> None:
            @runtime_checkable
            class _HasSyncClose(Protocol):
                def close(self) -> None: ...

            if isinstance(self._c, _HasSyncClose):
                self._c.close()

    return _RedisSyncWrapper(client)


__all__ = [
    "RedisAsyncProtocol",
    "RedisSyncProtocol",
    "_PipelineProtocol",
    "wrap_redis_async",
    "wrap_redis_sync",
]
