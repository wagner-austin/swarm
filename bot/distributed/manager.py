"""
Job Manager - Unified Worker System
----------------------------------
Orchestrates job distribution and handles callbacks to frontends.
Bridges the gap between Discord/Telegram/Web frontends and generic workers.
"""

import asyncio
import json
import logging
import os
import platform
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import psutil
from aiohttp import web

from bot.core.deployment_context import (
    DeploymentContextProvider,
    default_deployment_context_provider,
)
from bot.core.logger_setup import setup_logging

from .broker import Broker
from .model import Job


@dataclass
class JobResult:
    """Result of a completed job."""

    job_id: str
    success: bool
    result: Any | None = None
    error: str | None = None


logger = logging.getLogger(__name__)


class JobManager:
    """
    Manages job distribution and frontend callbacks.

    Flow:
    1. Frontend sends job request via Redis pub/sub
    2. Manager enqueues job to worker queue
    3. Manager listens for job completion
    4. Manager sends results back to frontend
    """

    def __init__(self, redis_url: str):
        super().__init__()
        self.broker = Broker(redis_url)
        self.running = False
        self.active_jobs: dict[str, dict[str, Any]] = {}
        self.tasks: list[asyncio.Task[Any]] = []

    async def start(self, http_port: int) -> None:
        """Start the manager service."""
        logger.info("🎯 Starting Job Manager...")
        self.running = True

        logger.info("🚀 Starting background tasks...")
        self.tasks = [
            asyncio.create_task(self._listen_for_job_requests()),
            asyncio.create_task(self._listen_for_job_results()),
            asyncio.create_task(self._cleanup_expired_jobs()),
            asyncio.create_task(self._start_http_server(http_port)),
        ]

        logger.info("✅ Job Manager started successfully")
        try:
            await asyncio.gather(*self.tasks)
        except asyncio.CancelledError:
            logger.info("Background tasks cancelled")

    async def stop(self) -> None:
        """Stop the manager service."""
        logger.info("🛑 Stopping Job Manager...")
        self.running = False

        # Cancel background tasks
        if hasattr(self, "tasks"):
            for task in self.tasks:
                task.cancel()
            await asyncio.gather(*self.tasks, return_exceptions=True)
            logger.info("✅ Background tasks stopped")

    async def _listen_for_job_requests(self) -> None:
        """Listen for job requests from frontends."""
        logger.info("👂 Listening for job requests...")

        while self.running:
            try:
                # Listen on job_requests channel
                message = await self.broker._r.blpop("job_requests", timeout=1)
                if not message:
                    continue

                request_data = json.loads(message[1])
                await self._handle_job_request(request_data)

            except Exception as e:
                logger.error(f"Error processing job request: {e}")
                await asyncio.sleep(1)

    async def _handle_job_request(self, request_data: dict[str, Any]) -> None:
        """Handle a job request from a frontend."""
        try:
            # Extract request details
            job_data = request_data["job"]
            callback_info = request_data["callback"]

            # Create job
            job = Job(
                id=job_data["id"],
                type=job_data["type"],
                args=tuple(job_data.get("args", [])),
                kwargs=job_data.get("kwargs", {}),
                reply_to="job_results",  # Workers send results here
                created_ts=time.time(),
            )

            # Track for callback
            self.active_jobs[job.id] = callback_info

            # Enqueue to workers
            await self.broker.publish(job)

            logger.info(f"📋 Job {job.id} enqueued from {callback_info.get('frontend', 'unknown')}")

        except Exception as e:
            logger.error(f"Failed to handle job request: {e}")

    async def _listen_for_job_results(self) -> None:
        """Listen for job completion from workers."""
        logger.info("👂 Listening for job results...")

        while self.running:
            try:
                # Listen on job_results channel
                message = await self.broker._r.blpop("job_results", timeout=1)
                if not message:
                    continue

                result_data = json.loads(message[1])
                await self._handle_job_result(result_data)

            except Exception as e:
                logger.error(f"Error processing job result: {e}")
                await asyncio.sleep(1)

    async def _handle_job_result(self, result_data: dict[str, Any]) -> None:
        """Handle job completion and send callback to frontend."""
        try:
            job_id = result_data["job_id"]

            # Get callback info
            callback_info = self.active_jobs.get(job_id)
            if not callback_info:
                logger.warning(f"No callback info found for job {job_id}")
                return

            # Send result to frontend
            callback_channel = callback_info["channel"]
            callback_payload = {
                "job_id": job_id,
                "result": result_data,
                "callback_info": callback_info,
            }

            await self.broker._r.rpush(callback_channel, json.dumps(callback_payload))

            # Clean up
            del self.active_jobs[job_id]

            logger.info(
                f"✅ Job {job_id} completed, callback sent to {callback_info.get('frontend')}"
            )

        except Exception as e:
            logger.error(f"Failed to handle job result: {e}")

    async def _cleanup_expired_jobs(self) -> None:
        """Clean up jobs that have been active too long."""
        while self.running:
            try:
                # TODO: Add timestamp tracking and cleanup logic
                await asyncio.sleep(300)  # Check every 5 minutes
            except Exception as e:
                logger.error(f"Error in job cleanup: {e}")
                await asyncio.sleep(60)

    def get_status(self) -> dict[str, Any]:
        """Get manager status for monitoring."""
        return {
            "service": "job_manager",
            "active_jobs": len(self.active_jobs),
            "running": self.running,
        }

    async def _start_http_server(self, port: int) -> None:
        """Start the HTTP server for health and metrics."""
        app = web.Application()
        app["manager"] = self
        app["deployment_context_provider"] = default_deployment_context_provider
        app.router.add_get("/health", self._health_handler)
        app.router.add_get("/metrics", self._metrics_handler)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        try:
            await site.start()
            logger.info(f"🚀 HTTP server started on port {port}")
            while self.running:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            pass
        finally:
            await runner.cleanup()
            logger.info("🛑 HTTP server stopped.")

    async def _health_handler(self, request: web.Request) -> web.Response:
        """Handle health check requests."""
        manager = request.app["manager"]
        status_data = manager.get_status()

        try:
            process = psutil.Process()
            health_data = {
                "status": "healthy",
                **status_data,
                "resources": {
                    "memory_mb": round(process.memory_info().rss / 1024 / 1024, 2),
                    "cpu_percent": process.cpu_percent(),
                },
                "timestamp": time.time(),
            }
            return web.json_response(health_data, status=200)
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return web.json_response({"status": "unhealthy", "error": str(e)}, status=503)

    async def _metrics_handler(self, request: web.Request) -> web.Response:
        """Handle Prometheus metrics requests."""
        manager = request.app["manager"]
        status_data = manager.get_status()

        deployment_context_provider: DeploymentContextProvider = request.app[
            "deployment_context_provider"
        ]
        context = deployment_context_provider()

        labels = (
            f'service="manager",'
            f'hostname="{context["hostname"]}",'
            f'container_id="{context["container_id"]}",'
            f'deployment_env="{context["deployment_env"]}",'
            f'region="{context["region"]}"'
        )

        lines = [
            "# HELP manager_active_jobs Number of jobs currently being managed.",
            "# TYPE manager_active_jobs gauge",
            f"manager_active_jobs{{{labels}}} {status_data['active_jobs']}",
        ]

        return web.Response(text="\n".join(lines), content_type="text/plain")


async def main() -> None:
    """Run the manager service."""
    setup_logging()

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    metrics_port = int(os.getenv("METRICS_PORT", "9150"))

    manager = JobManager(redis_url)

    try:
        await manager.start(http_port=metrics_port)
    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
    finally:
        await manager.stop()


if __name__ == "__main__":
    asyncio.run(main())
