"""
Common type aliases for the Swarm project.
"""

from typing import TYPE_CHECKING, TypeAlias

import redis
from redis.asyncio import Redis

if TYPE_CHECKING:
    # For type checking, we can use the generic form
    RedisBytes: TypeAlias = Redis[bytes]
    RedisSyncBytes: TypeAlias = redis.Redis[bytes]
else:
    # At runtime, Redis is not generic, so we use the plain class
    RedisBytes = Redis
    RedisSyncBytes = redis.Redis
