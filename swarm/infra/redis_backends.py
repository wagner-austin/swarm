"""
Redis backend abstraction layer for automatic failover between Upstash and local Redis.

This module provides a production-grade abstraction that:
1. Detects Upstash rate limits and switches to local Redis
2. Provides health monitoring and circuit breaker patterns
3. Integrates with existing logging and metrics infrastructure
4. Avoids brittle if/else chains through strategy pattern
"""

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Protocol, cast, runtime_checkable

import redis.asyncio as redis
from prometheus_client import Counter, Histogram
from redis.asyncio import Redis
from redis.exceptions import ResponseError

from swarm.core.exceptions import RedisConnectionError, RedisRateLimitError
from swarm.core.telemetry import REGISTRY

logger = logging.getLogger(__name__)

# Redis backend metrics
REDIS_OPERATION_TOTAL = Counter(
    "redis_operation_total",
    "Redis operations by backend and status",
    ["backend", "operation", "status"],
    registry=REGISTRY,
)
REDIS_OPERATION_LATENCY = Histogram(
    "redis_operation_latency_seconds",
    "Redis operation latency by backend",
    ["backend", "operation"],
    registry=REGISTRY,
)
REDIS_FAILOVER_TOTAL = Counter(
    "redis_failover_total",
    "Redis failover events",
    ["event_type"],  # activated, restored, circuit_open
    registry=REGISTRY,
)


@runtime_checkable
class RedisBackend(Protocol):
    """Protocol for Redis backend implementations."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Backend name for logging and metrics."""
        ...

    @property
    @abstractmethod
    def is_healthy(self) -> bool:
        """Check if backend is currently healthy."""
        ...

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to Redis."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Close Redis connection."""
        ...

    @abstractmethod
    async def execute(self, method: str, *args: Any, **kwargs: Any) -> Any:
        """Execute a Redis command."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Perform health check on the backend."""
        ...


class BaseRedisBackend(ABC):
    """Base implementation for Redis backends with common functionality."""

    def __init__(self, url: str, max_retries: int = 3, retry_delay: float = 1.0):
        self.url = url
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._client: Redis[Any] | None = None
        self._healthy = True
        self._last_health_check = 0.0
        self._health_check_interval = 30.0  # seconds
        self._failure_count = 0
        self._circuit_breaker_threshold = 5
        self._circuit_breaker_reset_time = 60.0
        self._circuit_open_until = 0.0

    @property
    @abstractmethod
    def name(self) -> str:
        """Backend name for logging and metrics."""
        ...

    @property
    def is_healthy(self) -> bool:
        """Check if backend is currently healthy."""
        if time.time() < self._circuit_open_until:
            return False
        return self._healthy

    async def connect(self) -> None:
        """Establish connection to Redis."""
        if self._client:
            await self.disconnect()

        try:
            self._client = redis.from_url(
                self.url,
                decode_responses=True,
                socket_keepalive=True,
                socket_keepalive_options={
                    1: 1,  # TCP_KEEPIDLE
                    2: 3,  # TCP_KEEPINTVL
                    3: 5,  # TCP_KEEPCNT
                },
            )
            assert self._client is not None
            await self._client.ping()
            self._healthy = True
            self._failure_count = 0
            logger.info(f"{self.name} backend connected successfully")
            REDIS_OPERATION_TOTAL.labels(self.name, "connect", "success").inc()
        except Exception as e:
            self._healthy = False
            logger.error(f"{self.name} backend connection failed: {e}")
            REDIS_OPERATION_TOTAL.labels(self.name, "connect", "failure").inc()
            raise RedisConnectionError(self.name, str(e))

    async def disconnect(self) -> None:
        """Close Redis connection."""
        if self._client:
            await self._client.close()
            self._client = None
            logger.info(f"{self.name} backend disconnected")

    async def execute(self, method: str, *args: Any, **kwargs: Any) -> Any:
        """Execute a Redis command with retry logic."""
        if not self._client:
            raise RedisConnectionError(self.name, "Not connected")

        if not self.is_healthy:
            raise RedisConnectionError(self.name, "Backend is unhealthy (circuit breaker open)")

        last_error = None
        for attempt in range(self.max_retries):
            try:
                result = await getattr(self._client, method)(*args, **kwargs)
                self._on_success()
                return result
            except Exception as e:
                last_error = e
                self._on_failure(e)

                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                    logger.warning(
                        f"{self.name} command {method} failed (attempt {attempt + 1}/{self.max_retries}): {e}"
                    )

        REDIS_OPERATION_TOTAL.labels(self.name, method, "failure").inc()
        if last_error is None:
            last_error = Exception("Unknown error")
        raise last_error

    async def health_check(self) -> bool:
        """Perform health check on the backend."""
        current_time = time.time()

        # Skip if checked recently
        if current_time - self._last_health_check < self._health_check_interval:
            return self.is_healthy

        self._last_health_check = current_time

        try:
            if self._client:
                await self._client.ping()
                self._healthy = True
                self._failure_count = 0
                return True
        except Exception as e:
            logger.warning(f"{self.name} health check failed: {e}")
            self._healthy = False

        return False

    def _on_success(self) -> None:
        """Handle successful operation."""
        self._failure_count = 0

    def _on_failure(self, error: Exception) -> None:
        """Handle failed operation."""
        self._failure_count += 1

        # Open circuit breaker if threshold reached
        if self._failure_count >= self._circuit_breaker_threshold:
            self._circuit_open_until = time.time() + self._circuit_breaker_reset_time
            logger.error(
                f"{self.name} circuit breaker opened due to {self._failure_count} consecutive failures"
            )
            REDIS_FAILOVER_TOTAL.labels("circuit_open").inc()


class UpstashRedisBackend(BaseRedisBackend):
    """Upstash Redis backend with rate limit detection."""

    @property
    def name(self) -> str:
        return "upstash"

    async def execute(self, method: str, *args: Any, **kwargs: Any) -> Any:
        """Execute command with Upstash rate limit detection."""
        try:
            return await super().execute(method, *args, **kwargs)
        except ResponseError as e:
            error_msg = str(e).lower()
            if "max requests limit exceeded" in error_msg:
                # Parse limit and usage from error message
                import re

                match = re.search(r"limit:\s*(\d+),\s*usage:\s*(\d+)", error_msg, re.IGNORECASE)
                if match:
                    limit = int(match.group(1))
                    usage = int(match.group(2))
                    logger.error(f"Upstash rate limit exceeded: {usage}/{limit}")
                    REDIS_OPERATION_TOTAL.labels("upstash", "rate_limit", "exceeded").inc()
                    self._healthy = False
                    raise RedisRateLimitError(limit, usage)
            raise


class LocalRedisBackend(BaseRedisBackend):
    """Local Redis backend (Docker/self-hosted)."""

    @property
    def name(self) -> str:
        return "local"


class FallbackRedisBackend:
    """
    Redis backend that automatically falls back from primary to fallback backend.

    This implements the RedisBackend protocol and manages automatic failover
    without brittle if/else chains.
    """

    def __init__(self, primary: RedisBackend, fallback: RedisBackend):
        self.primary = primary
        self.fallback = fallback
        self._using_fallback = False
        self._fallback_until = 0.0
        self._retry_primary_interval = 300.0  # 5 minutes

    @property
    def name(self) -> str:
        return f"fallback({self.primary.name}->{self.fallback.name})"

    @property
    def is_healthy(self) -> bool:
        return self._current_backend.is_healthy

    @property
    def _current_backend(self) -> RedisBackend:
        """Get the currently active backend."""
        # Check if we should retry primary
        if self._using_fallback and time.time() > self._fallback_until:
            asyncio.create_task(self._try_primary())

        return self.fallback if self._using_fallback else self.primary

    async def connect(self) -> None:
        """Connect to primary, fallback if it fails."""
        try:
            await self.primary.connect()
            self._using_fallback = False
            logger.info("Connected to primary Redis backend")
        except Exception as e:
            logger.warning(f"Primary backend connection failed: {e}, trying fallback")
            await self.fallback.connect()
            self._using_fallback = True
            self._fallback_until = time.time() + self._retry_primary_interval
            logger.info("Connected to fallback Redis backend")
            REDIS_FAILOVER_TOTAL.labels("activated").inc()

    async def disconnect(self) -> None:
        """Disconnect from both backends."""
        await self.primary.disconnect()
        await self.fallback.disconnect()

    async def execute(self, method: str, *args: Any, **kwargs: Any) -> Any:
        """Execute command on current backend, fallback if needed."""
        if not self._using_fallback:
            try:
                return await self.primary.execute(method, *args, **kwargs)
            except (RedisRateLimitError, RedisConnectionError) as e:
                logger.warning(f"Primary backend failed: {e}, switching to fallback")
                await self._switch_to_fallback()
                return await self.fallback.execute(method, *args, **kwargs)
        else:
            return await self.fallback.execute(method, *args, **kwargs)

    async def health_check(self) -> bool:
        """Check health of current backend."""
        return await self._current_backend.health_check()

    async def _switch_to_fallback(self) -> None:
        """Switch to fallback backend."""
        if not self._using_fallback:
            self._using_fallback = True
            self._fallback_until = time.time() + self._retry_primary_interval

            # Ensure fallback is connected
            try:
                await self.fallback.health_check()
            except Exception:
                await self.fallback.connect()

            logger.info("Switched to fallback Redis backend")
            REDIS_FAILOVER_TOTAL.labels("activated").inc()

    async def _try_primary(self) -> None:
        """Try to reconnect to primary backend."""
        try:
            await self.primary.health_check()
            if self.primary.is_healthy:
                self._using_fallback = False
                logger.info("Switched back to primary Redis backend")
                REDIS_FAILOVER_TOTAL.labels("restored").inc()
        except Exception:
            # Stay on fallback
            self._fallback_until = time.time() + self._retry_primary_interval
