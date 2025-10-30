"""
Common type aliases and Protocols for the Swarm project.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, TypeAlias

import redis
from redis.asyncio import Redis

if TYPE_CHECKING:
    # For type checking, use generic forms to convey value types
    from discord.ext import commands as discord_commands

    from swarm.core.containers import Container
    from swarm.core.lifecycle import SwarmLifecycle
    from swarm.core.settings import Settings

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


class ContainerFactory(Protocol):
    def __call__(self, settings: Settings) -> Container: ...


class CogFactory(Protocol):
    def __call__(
        self,
        *,
        discord_bot: discord_commands.Bot,
        lifecycle: SwarmLifecycle | None = None,
    ) -> discord_commands.Cog: ...
