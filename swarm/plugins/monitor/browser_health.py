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
from swarm.plugins.base_di import BaseDIClientCog
from swarm.types import RedisBytes

logger = logging.getLogger(__name__)


class BrowserHealthStatus(TypedDict):
    """Typed shape for cached browser health status."""

    healthy_workers: int
    is_degraded: bool
    last_check: float
    min_required: int
    healthy: bool
    error: NotRequired[str]


STALE_WINDOW_SECONDS: float = 90.0


class BrowserHealthMonitor(BaseDIClientCog):
    """Monitors browser worker health via Redis heartbeats only."""

    def __init__(self, *, discord_bot: commands.Bot, redis: RedisBytes | None = None) -> None:
        super().__init__(discord_bot)
        self.bot = discord_bot
        self.monitoring_task: asyncio.Task[None] | None = None
        self.check_interval = 60.0  # Check every 60 seconds
        self.min_healthy_workers = 1

        # Expose Redis client from DI for snapshot persistence (optional)
        self.redis: RedisBytes | None = redis

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

            keys: list[bytes] = await self.redis.keys("worker:heartbeat:browser:*")
            fresh = 0
            for k in keys:
                key_str = k.decode()
                ts_raw = await self.redis.hget(key_str, "timestamp")
                if ts_raw is None:
                    continue
                ts_str = ts_raw.decode() if isinstance(ts_raw, (bytes | bytearray)) else str(ts_raw)
                try:
                    ts = float(ts_str)
                except Exception:
                    continue
                if current_time - ts <= STALE_WINDOW_SECONDS:
                    fresh += 1
            healthy_workers = fresh

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
            await self.redis.hset(
                "browser:health",
                mapping={
                    "healthy_workers": str(healthy_workers),
                    "is_degraded": "true" if is_degraded else "false",
                    "last_check": str(current_time),
                    "min_required": str(self.min_healthy_workers),
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
