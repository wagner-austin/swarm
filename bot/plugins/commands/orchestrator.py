"""
Orchestrator - Dynamic Worker Management
========================================

Manages a fleet of distributed workers, handling:
- Dynamic worker spawning based on demand
- Job routing to appropriate worker types
- Load balancing across workers
- Health monitoring and auto-recovery
- Scaling policies
"""

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

from bot.core.exceptions import WorkerUnavailableError
from bot.distributed.broker import Broker
from bot.distributed.core.pool import WorkerPool
from bot.distributed.model import Job
from bot.distributed.services.scaling_service import ScalingService
from bot.frontends.discord.discord_interactions import safe_send
from bot.frontends.discord.discord_owner import get_owner
from bot.plugins.base_di import BaseDIClientCog

logger = logging.getLogger(__name__)


class Orchestrator(BaseDIClientCog):
    """
    Orchestrates distributed workers for the bot.

    Responsibilities:
    - Monitor job queues and worker health
    - Route jobs to appropriate workers
    - Scale workers based on demand
    - Provide visibility into the worker fleet
    """

    def __init__(
        self,
        bot: commands.Bot,
        broker: Broker,
        redis_client: Any,
        scaling_service: ScalingService,
        safe_send_func: Any = safe_send,
    ):
        super().__init__(bot)
        self.broker = broker
        self.redis = redis_client
        self.scaling_service = scaling_service
        self.safe_send = safe_send_func

        # Worker pools by type - using the shared WorkerPool class
        self.pools = {
            "browser": WorkerPool("browser"),
            "tankpit": WorkerPool("tankpit"),
        }

        self.pending_jobs: dict[str, dict[str, Any]] = {}  # job_id -> job info

    async def cog_load(self) -> None:
        """Start background tasks when cog loads."""
        self.monitor_workers.start()
        self.monitor_queues.start()
        self.cleanup_stale.start()

    async def cog_unload(self) -> None:
        """Stop background tasks when cog unloads."""
        self.monitor_workers.cancel()
        self.monitor_queues.cancel()
        self.cleanup_stale.cancel()

    @tasks.loop(seconds=10)
    async def monitor_workers(self) -> None:
        """Monitor worker health via heartbeats."""
        try:
            # Check for worker heartbeats in Redis
            for pool_name, pool in self.pools.items():
                # Get all workers that have sent heartbeats
                pattern = f"worker:heartbeat:{pool_name}:*"
                cursor = 0
                while True:
                    cursor, keys = await self.redis.scan(cursor, match=pattern, count=100)

                    for key in keys:
                        # Handle both bytes and str keys from Redis
                        key_str = key.decode("utf-8") if isinstance(key, bytes) else key
                        worker_id = key_str.split(":")[-1]
                        # Get state from Redis hash (not string)
                        state = await self.redis.hget(key_str, "state")

                        if state:
                            # Worker is healthy if it has a state
                            pool.register_worker(worker_id, {})
                            pool.mark_healthy(worker_id)

                    if cursor == 0:
                        break

        except Exception as e:
            logger.error(f"Error monitoring workers: {e}")

    @tasks.loop(seconds=15)
    async def monitor_queues(self) -> None:
        """Monitor job queues and store metrics."""
        try:
            for job_type in ["browser", "tankpit"]:
                # Get queue depth
                queue_name = f"{job_type}:jobs"
                queue_depth = await self.redis.xlen(queue_name)

                # Get worker count
                pool = self.pools[job_type]
                healthy_workers = len(pool.get_healthy_workers())

                # Store metrics
                await self.redis.hset(
                    "orchestrator:metrics",
                    f"{job_type}_queue_depth",
                    queue_depth,
                )
                await self.redis.hset(
                    "orchestrator:metrics",
                    f"{job_type}_workers",
                    healthy_workers,
                )

                # DO NOT trigger scaling - that's the autoscaler's job!
                # The autoscaler service runs separately and monitors these metrics

        except Exception as e:
            logger.error(f"Error monitoring queues: {e}")

    @tasks.loop(seconds=60)
    async def cleanup_stale(self) -> None:
        """Clean up stale workers and jobs."""
        try:
            for pool in self.pools.values():
                removed = pool.remove_stale_workers()
                if removed:
                    logger.info(f"Removed stale workers: {removed}")

            # Clean up old pending jobs
            now = time.time()
            for job_id in list(self.pending_jobs.keys()):
                if now - self.pending_jobs[job_id]["created_at"] > 300:  # 5 min timeout
                    del self.pending_jobs[job_id]

        except Exception as e:
            logger.error(f"Error in cleanup: {e}")

    async def _request_scale_up(self, job_type: str, target_count: int) -> None:
        """Request scale up using the scaling service."""
        logger.info(f"📈 Scaling up {job_type} workers to {target_count}")

        # Use the scaling service to handle the actual scaling
        if self.scaling_service.backend:
            success = await self.scaling_service.backend.scale_to(job_type, target_count)
        else:
            logger.error("No scaling backend configured")
            success = False

        if success:
            # Store the request for tracking
            await self.redis.hset(
                "orchestrator:scaling_requests",
                f"{job_type}_target",
                target_count,
            )
        else:
            logger.error(f"Failed to scale up {job_type} workers")

    async def _request_scale_down(self, job_type: str, target_count: int) -> None:
        """Request scale down using the scaling service."""
        logger.info(f"📉 Scaling down {job_type} workers to {target_count}")

        # Use the scaling service to handle the actual scaling
        if self.scaling_service.backend:
            success = await self.scaling_service.backend.scale_to(job_type, target_count)
        else:
            logger.error("No scaling backend configured")
            success = False

        if success:
            await self.redis.hset(
                "orchestrator:scaling_requests",
                f"{job_type}_target",
                target_count,
            )
        else:
            logger.error(f"Failed to scale down {job_type} workers")

    @app_commands.command(name="workers", description="Show worker fleet status (owner only)")
    async def workers_status(self, interaction: discord.Interaction) -> None:
        """Show status of all workers."""
        await interaction.response.defer(ephemeral=True)

        # Owner check
        try:
            owner = await get_owner(self.bot)
        except RuntimeError:
            await self.safe_send(interaction, "❌ Could not resolve bot owner.", ephemeral=True)
            return

        if interaction.user.id != owner.id:
            await self.safe_send(interaction, "❌ Owner only.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🤖 Worker Fleet Status",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow(),
        )

        # Get metrics
        metrics = await self.redis.hgetall("orchestrator:metrics")

        for pool_name, pool in self.pools.items():
            healthy = pool.get_healthy_workers()
            queue_depth = int(metrics.get(f"{pool_name}_queue_depth", 0))

            embed.add_field(
                name=f"{pool_name.title()} Workers",
                value=(
                    f"**Healthy:** {len(healthy)}\n"
                    f"**Total:** {len(pool.workers)}\n"
                    f"**Queue:** {queue_depth} jobs"
                ),
                inline=True,
            )

        # Add scaling info
        scaling_requests = await self.redis.hgetall("orchestrator:scaling_requests")
        if scaling_requests:
            scaling_info = "\n".join(f"{k}: {v}" for k, v in scaling_requests.items())
            embed.add_field(
                name="📊 Scaling Requests",
                value=scaling_info or "None",
                inline=False,
            )

        await self.safe_send(interaction, embed=embed)

    @app_commands.command(name="scale", description="Manually scale workers (owner only)")
    async def scale_workers(
        self,
        interaction: discord.Interaction,
        worker_type: str,
        count: int,
    ) -> None:
        """Manually scale workers."""
        await interaction.response.defer(ephemeral=True)

        # Owner check
        try:
            owner = await get_owner(self.bot)
        except RuntimeError:
            await self.safe_send(interaction, "❌ Could not resolve bot owner.", ephemeral=True)
            return

        if interaction.user.id != owner.id:
            await self.safe_send(interaction, "❌ Owner only.", ephemeral=True)
            return

        if worker_type not in self.pools:
            await self.safe_send(
                interaction,
                "❌ Invalid worker type. Choose 'browser' or 'tankpit'.",
            )
            return

        worker_config = self.scaling_service.config.get_worker_type(worker_type)
        if not worker_config:
            await self.safe_send(
                interaction,
                f"❌ No configuration found for worker type '{worker_type}'.",
            )
            return

        scaling_config = worker_config.scaling
        if count < scaling_config.min_workers or count > scaling_config.max_workers:
            await self.safe_send(
                interaction,
                f"❌ Count must be between {scaling_config.min_workers} and {scaling_config.max_workers}.",
            )
            return

        # Request scaling
        if count > len(self.pools[worker_type].get_healthy_workers()):
            await self._request_scale_up(worker_type, count)
            await self.safe_send(
                interaction,
                f"📈 Requested scale up of {worker_type} workers to {count}.",
            )
        else:
            await self._request_scale_down(worker_type, count)
            await self.safe_send(
                interaction,
                f"📉 Requested scale down of {worker_type} workers to {count}.",
            )

    @app_commands.command(name="dispatch", description="Dispatch a test job (owner only)")
    async def dispatch_job(
        self,
        interaction: discord.Interaction,
        job_type: str,
        command: str,
    ) -> None:
        """Manually dispatch a job for testing."""
        await interaction.response.defer(ephemeral=True)

        # Owner check
        try:
            owner = await get_owner(self.bot)
        except RuntimeError:
            await self.safe_send(interaction, "❌ Could not resolve bot owner.", ephemeral=True)
            return

        if interaction.user.id != owner.id:
            await self.safe_send(interaction, "❌ Owner only.", ephemeral=True)
            return

        # Create job
        job = Job(
            id=f"manual-{int(time.time() * 1000)}",
            type=job_type,
            args=(command,),
            kwargs={"channel_id": interaction.channel_id},
            reply_to="",
            created_ts=time.time(),
        )

        try:
            # Publish job
            await self.broker.publish(job)

            await self.safe_send(
                interaction,
                f"✅ Dispatched {job_type} job: {command}\nJob ID: {job.id}",
            )
        except WorkerUnavailableError:
            await self.safe_send(
                interaction,
                f"❌ No {job_type} workers available!",
            )
