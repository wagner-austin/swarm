"""
HTTP server for worker health and metrics endpoints.
Exposes /health (JSON) and /metrics (Prometheus text format).
"""

import asyncio
import os
import platform
import time
from typing import TYPE_CHECKING, Callable

import psutil
from aiohttp import web
from aiohttp.web_request import Request
from aiohttp.web_response import Response

from bot.core.deployment_context import (
    DeploymentContextProvider,
    default_deployment_context_provider,
)

from ..worker import Worker

WORKER_KEY = web.AppKey("worker", Worker)
START_TIME = time.time()


async def health(request: Request) -> Response:
    worker = request.app[WORKER_KEY]
    state = worker.get_state().name
    status = 200 if state not in ("ERROR", "SHUTDOWN") else 503

    # Collect system info
    try:
        process = psutil.Process()
        memory_info = process.memory_info()
        cpu_percent = process.cpu_percent()

        health_data = {
            "status": "healthy" if status == 200 else "unhealthy",
            "state": state,
            "worker_id": worker.worker_id,
            "uptime_seconds": time.time() - START_TIME,
            "system": {
                "hostname": platform.node(),
                "platform": platform.platform(),
                "python_version": platform.python_version(),
            },
            "resources": {
                "memory_mb": round(memory_info.rss / 1024 / 1024, 2),
                "memory_percent": round(process.memory_percent(), 2),
                "cpu_percent": cpu_percent,
                "num_threads": process.num_threads(),
            },
            "timestamp": time.time(),
        }
    except Exception as e:
        # Fallback if psutil fails
        health_data = {
            "status": "healthy" if status == 200 else "unhealthy",
            "state": state,
            "worker_id": worker.worker_id,
            "uptime_seconds": time.time() - START_TIME,
            "error": f"Could not collect system metrics: {e}",
            "timestamp": time.time(),
        }

    return web.json_response(health_data, status=status)


async def metrics(request: Request) -> Response:
    worker = request.app[WORKER_KEY]
    deployment_context_provider: DeploymentContextProvider = request.app.get(
        "deployment_context_provider", default_deployment_context_provider
    )
    context = deployment_context_provider()

    try:
        process = psutil.Process()
        memory_info = process.memory_info()

        # Use injected deployment metadata
        labels = (
            f'worker_id="{worker.worker_id}",'
            f'hostname="{context["hostname"]}",'
            f'container_id="{context["container_id"]}",'
            f'deployment_env="{context["deployment_env"]}",'
            f'region="{context["region"]}"'
        )

        lines = [
            "# HELP worker_state Current state of the worker (0=IDLE, 1=WAITING, 2=BUSY, 3=ERROR, 4=SHUTDOWN)",
            "# TYPE worker_state gauge",
            f"worker_state{{{labels}}} {worker.get_state().value}",
            "",
            "# HELP worker_uptime_seconds Worker uptime in seconds",
            "# TYPE worker_uptime_seconds counter",
            f"worker_uptime_seconds{{{labels}}} {time.time() - START_TIME}",
            "",
            "# HELP worker_backoff_seconds Current backoff delay in seconds",
            "# TYPE worker_backoff_seconds gauge",
            f"worker_backoff_seconds{{{labels}}} {worker._backoff}",
            "",
            "# HELP worker_memory_bytes Worker memory usage in bytes",
            "# TYPE worker_memory_bytes gauge",
            f"worker_memory_bytes{{{labels}}} {memory_info.rss}",
            "",
            "# HELP worker_memory_percent Worker memory usage as percentage of system memory",
            "# TYPE worker_memory_percent gauge",
            f"worker_memory_percent{{{labels}}} {process.memory_percent()}",
            "",
            "# HELP worker_cpu_percent Worker CPU usage percentage",
            "# TYPE worker_cpu_percent gauge",
            f"worker_cpu_percent{{{labels}}} {process.cpu_percent()}",
            "",
            "# HELP worker_threads_total Number of threads in worker process",
            "# TYPE worker_threads_total gauge",
            f"worker_threads_total{{{labels}}} {process.num_threads()}",
            "",
            "# HELP worker_open_files_total Number of open file handles",
            "# TYPE worker_open_files_total gauge",
            f"worker_open_files_total{{{labels}}} {len(process.open_files())}",
        ]

        # Add job statistics if available (assuming worker has these attributes)
        if hasattr(worker, "jobs_processed"):
            lines.extend(
                [
                    "",
                    "# HELP worker_jobs_processed_total Total number of jobs processed",
                    "# TYPE worker_jobs_processed_total counter",
                    f"worker_jobs_processed_total{{{labels}}} {getattr(worker, 'jobs_processed', 0)}",
                ]
            )

        if hasattr(worker, "jobs_failed"):
            lines.extend(
                [
                    "",
                    "# HELP worker_jobs_failed_total Total number of jobs that failed",
                    "# TYPE worker_jobs_failed_total counter",
                    f"worker_jobs_failed_total{{{labels}}} {getattr(worker, 'jobs_failed', 0)}",
                ]
            )

    except Exception as e:
        # Fallback metrics if system monitoring fails
        lines = [
            f'worker_state{{worker_id="{worker.worker_id}"}} {worker.get_state().value}',
            f'worker_backoff_seconds{{worker_id="{worker.worker_id}"}} {worker._backoff}',
            f'worker_metrics_error{{worker_id="{worker.worker_id}"}} 1  # {e}',
        ]

    return web.Response(text="\n".join(lines), content_type="text/plain")


async def start_http_server(
    worker: "Worker",
    port: int = 9200,
    deployment_context_provider: DeploymentContextProvider = default_deployment_context_provider,
) -> None:
    app = web.Application()
    app[WORKER_KEY] = worker
    app["deployment_context_provider"] = deployment_context_provider
    app.router.add_get("/health", health)
    app.router.add_get("/metrics", metrics)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    # Keep running forever (this task never returns)
    while True:
        await asyncio.sleep(3600)
