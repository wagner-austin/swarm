"""
Common type aliases for the Swarm project.
"""

from redis.asyncio import Redis as _Redis

# Redis type alias to avoid repeating generic parameters
type RedisBytes = _Redis[bytes]
