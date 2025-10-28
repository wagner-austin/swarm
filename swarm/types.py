"""
Common type aliases for the Swarm project.
"""

from typing import TYPE_CHECKING, TypeAlias

import redis
from redis.asyncio import Redis

if TYPE_CHECKING:
    # For type checking, use generic forms to convey value types
    RedisBytes: TypeAlias = Redis[bytes]
    RedisStr: TypeAlias = Redis[str]
    RedisSyncBytes: TypeAlias = redis.Redis[bytes]
    RedisSyncStr: TypeAlias = redis.Redis[str]
else:
    # At runtime, Redis is not generic, so use the plain classes
    RedisBytes = Redis
    RedisStr = Redis
    RedisSyncBytes = redis.Redis
    RedisSyncStr = redis.Redis
