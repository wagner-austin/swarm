"""
Browser Health Monitoring for Discord Bot
==========================================

Monitors worker heartbeats and sets degradation status when browser workers
become unavailable, providing fail-fast behavior for web commands.
"""

import asyncio
import logging
import time
from typing import Any

import redis.asyncio as redis_asyncio

from bot.plugins.base_di import BaseDIClientCog

logger = logging.getLogger(__name__)


class BrowserHealthMonitor(BaseDIClientCog):
    """
    Monitors browser worker heartbeats and tracks pool health.

    Sets BROWSER_DEGRADED status when fewer than minimum workers are healthy,
    enabling web commands to fail fast instead of timing out.
    """

    def __init__(self, bot: Any, redis_client: redis_asyncio.Redis) -> None:
        super().__init__(bot)
        self.redis = redis_client
        self.monitoring_task: asyncio.Task[None] | None = None
        self.check_interval = 15.0  # seconds
        self.min_healthy_workers = 1
        self.max_heartbeat_age = 60.0  # seconds

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
        """Check health of browser workers and update status."""
        try:
            # Get all worker heartbeats
            pattern = "worker:heartbeat:*"
            current_time = time.time()
            healthy_workers = 0

            keys = await self.redis.keys(pattern)
            for key in keys:
                if isinstance(key, bytes):
                    key = key.decode()

                # Get timestamp from heartbeat
                timestamp_bytes = await self.redis.hget(key, "timestamp")  # type: ignore[misc]
                if timestamp_bytes:
                    try:
                        timestamp = float(timestamp_bytes.decode())
                        if current_time - timestamp <= self.max_heartbeat_age:
                            healthy_workers += 1
                    except (ValueError, AttributeError):
                        continue

            # Update health status
            is_degraded = healthy_workers < self.min_healthy_workers

            # Store status in Redis for web commands to check
            await self.redis.hset(  # type: ignore[misc]
                "browser:health",
                mapping={
                    "healthy_workers": healthy_workers,
                    "is_degraded": str(is_degraded).lower(),
                    "last_check": current_time,
                    "min_required": self.min_healthy_workers,
                },
            )

            # Log status changes
            if is_degraded:
                logger.warning(
                    f"Browser pool DEGRADED: {healthy_workers}/{self.min_healthy_workers} workers healthy"
                )
            else:
                logger.debug(f"Browser pool healthy: {healthy_workers} workers active")

        except Exception as exc:
            logger.error(f"Failed to check worker health: {exc}", exc_info=True)

    async def get_health_status(self) -> dict[str, Any]:
        """Get current browser pool health status."""
        try:
            health_data = await self.redis.hgetall("browser:health")  # type: ignore[misc]
            if not health_data:
                return {"healthy": False, "error": "No health data available"}

            return {
                "healthy_workers": int(health_data.get(b"healthy_workers", 0)),
                "is_degraded": health_data.get(b"is_degraded", b"true").decode() == "true",
                "last_check": float(health_data.get(b"last_check", 0)),
                "min_required": int(health_data.get(b"min_required", 1)),
            }
        except Exception as exc:
            logger.error(f"Failed to get health status: {exc}")
            return {"healthy": False, "error": str(exc)}


async def setup(bot: Any) -> None:
    """Load the browser health monitoring cog."""
    from bot.core.containers import Container

    if hasattr(bot, "container"):
        container: Container = bot.container
        redis_client = container.redis_client()
        await bot.add_cog(BrowserHealthMonitor(bot, redis_client))
    else:
        logger.warning("Bot container not available, skipping browser health monitoring")
