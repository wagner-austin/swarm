"""
Browser Health Monitoring for Discord frontend
==============================================

Single source of truth for liveness: Redis heartbeats.
Counts fresh heartbeat keys for browser workers, caches status, and persists a
Redis snapshot for other components to read (e.g., web command health gate).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import NotRequired, TypedDict

from discord.ext import commands

from swarm.core.telemetry import (
    BROWSER_DEGRADED,
    BROWSER_HEALTH_LAST_CHECK_SECONDS,
    BROWSER_HEALTHY_WORKERS,
)
from swarm.infra.redis_keys import HEALTH_KEY, heartbeat_scan_pattern
from swarm.infra.redis_protocols import RedisAsyncProtocol
from swarm.plugins.base_di import BaseDIClientCog

logger = logging.getLogger(__name__)


class BrowserHealthStatus(TypedDict):
    """Typed shape for cached browser health status."""

    healthy_workers: int
    is_degraded: bool
    last_check: float
    min_required: int
    healthy: bool
    error: NotRequired[str]


# Liveness via TTL on standardized heartbeat keys.


async def write_health_snapshot(redis: RedisAsyncProtocol, status: BrowserHealthStatus) -> None:
    """Persist browser health snapshot as a Redis hash.

    Converts values to strings and stores under HEALTH_KEY.
    """
    await redis.hset(
        HEALTH_KEY,
        mapping={
            "healthy_workers": str(int(status.get("healthy_workers", 0))),
            "is_degraded": "true" if bool(status.get("is_degraded", True)) else "false",
            "last_check": str(float(status.get("last_check", 0.0))),
            "min_required": str(int(status.get("min_required", 1))),
        },
    )


async def read_health_snapshot(redis: RedisAsyncProtocol) -> BrowserHealthStatus | None:
    """Read and normalize the browser health snapshot.

    Returns a BrowserHealthStatus dict or None if not present.
    """
    raw = await redis.hgetall(HEALTH_KEY)
    if not raw:
        return None

    def _to_str(v: object) -> str:
        if isinstance(v, bytes | bytearray):
            try:
                return v.decode()
            except Exception:
                return ""
        return str(v)

    # Normalize keys to strings to handle clients that return bytes keys
    raw_norm: dict[str, object] = {
        (_to_str(k)): v for k, v in (raw.items() if isinstance(raw, dict) else [])
    }

    healthy_workers_s = _to_str(raw_norm.get("healthy_workers", "0"))
    is_degraded_s = _to_str(raw_norm.get("is_degraded", "true"))
    last_check_s = _to_str(raw_norm.get("last_check", "0.0"))
    min_required_s = _to_str(raw_norm.get("min_required", "1"))

    try:
        healthy_workers = int(healthy_workers_s)
    except Exception:
        healthy_workers = 0
    is_degraded = is_degraded_s.strip().lower() in {"1", "true", "yes"}
    try:
        last_check = float(last_check_s)
    except Exception:
        last_check = 0.0
    try:
        min_required = int(min_required_s)
    except Exception:
        min_required = 1

    return {
        "healthy_workers": healthy_workers,
        "is_degraded": is_degraded,
        "last_check": last_check,
        "min_required": min_required,
        "healthy": not is_degraded,
    }


class BrowserHealthMonitor(BaseDIClientCog):
    """Monitors browser worker health via Redis heartbeats only."""

    def __init__(
        self, *, discord_bot: commands.Bot, redis: RedisAsyncProtocol | None = None
    ) -> None:
        super().__init__(discord_bot)
        self.bot = discord_bot
        self.monitoring_task: asyncio.Task[None] | None = None
        self.check_interval = 60.0  # Check every 60 seconds
        self.min_healthy_workers = 1

        # Expose Redis client from DI for snapshot persistence (optional)
        self.redis: RedisAsyncProtocol | None = redis

        # Cached status
        self._cached_status: BrowserHealthStatus = {
            "healthy_workers": 0,
            "is_degraded": True,
            "last_check": 0.0,
            "min_required": self.min_healthy_workers,
            "healthy": False,
        }

    async def cog_load(self) -> None:
        """Start background health monitoring when cog loads."""
        logger.info("Starting browser health monitoring")
        # Immediate first check to avoid warm-up window
        try:
            await self._check_worker_health()
        except Exception as exc:
            logger.warning(f"Initial browser health check failed: {exc}")
        self.monitoring_task = asyncio.create_task(self._monitoring_loop())

    async def cog_unload(self) -> None:
        """Stop background monitoring when cog unloads."""
        if self.monitoring_task:
            logger.info("Stopping browser health monitoring")
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass
            finally:
                self.monitoring_task = None

    async def _monitoring_loop(self) -> None:
        """Check worker health periodically in monitoring loop."""
        while True:
            try:
                await self._check_worker_health()
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Error in browser health monitoring: {exc}", exc_info=True)
                await asyncio.sleep(self.check_interval)

    async def _check_worker_health(self) -> None:
        """Check health of browser workers via Redis heartbeats."""
        current_time = time.time()
        healthy_workers = 0

        try:
            if self.redis is None:
                raise RuntimeError("Redis client unavailable for health aggregation")

            from swarm.infra.redis_lua import count_ttl_healthy_by_scan

            # Single server-side scan + TTL count via Lua (one command)
            healthy_workers = await count_ttl_healthy_by_scan(
                self.redis, pattern=heartbeat_scan_pattern(), scan_count=1000
            )

            is_degraded = healthy_workers < self.min_healthy_workers

            # Update cached status
            self._cached_status = {
                "healthy_workers": healthy_workers,
                "is_degraded": is_degraded,
                "last_check": current_time,
                "min_required": self.min_healthy_workers,
                "healthy": not is_degraded,
            }

            # Persist health snapshot for fast reads
            await write_health_snapshot(
                self.redis,
                {
                    "healthy_workers": healthy_workers,
                    "is_degraded": is_degraded,
                    "last_check": current_time,
                    "min_required": self.min_healthy_workers,
                    "healthy": not is_degraded,
                },
            )

            # Export Prometheus metrics
            BROWSER_HEALTHY_WORKERS.set(healthy_workers)
            BROWSER_DEGRADED.set(1 if is_degraded else 0)
            BROWSER_HEALTH_LAST_CHECK_SECONDS.set(current_time)

            # Log status
            if is_degraded:
                logger.warning(
                    f"Browser pool DEGRADED: {healthy_workers}/{self.min_healthy_workers} workers healthy"
                )
            else:
                logger.info(f"Browser pool healthy: {healthy_workers} workers active")

        except Exception as exc:
            logger.error(f"Failed to check worker health: {exc}", exc_info=True)
            # Mark as degraded on error
            self._cached_status = {
                "healthy_workers": 0,
                "is_degraded": True,
                "last_check": current_time,
                "min_required": self.min_healthy_workers,
                "healthy": False,
                "error": str(exc),
            }

    def get_health_status(self) -> BrowserHealthStatus:
        """Get current browser pool health status from cache."""
        return self._cached_status.copy()


async def setup(discord_bot: commands.Bot) -> None:
    """Load the browser health monitoring cog."""
    await discord_bot.add_cog(BrowserHealthMonitor(discord_bot=discord_bot))
