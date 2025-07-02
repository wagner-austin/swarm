"""
HTTP server for worker health and metrics endpoints.
Exposes /health (JSON) and /metrics (Prometheus text format).
"""

import asyncio
from typing import TYPE_CHECKING

from aiohttp import web
from aiohttp.web_request import Request
from aiohttp.web_response import Response

if TYPE_CHECKING:
    from ..worker import Worker

WORKER_KEY: web.AppKey["Worker"] = web.AppKey("worker")


async def health(request: Request) -> Response:
    worker = request.app[WORKER_KEY]
    state = worker.get_state().name
    status = 200 if state not in ("ERROR", "SHUTDOWN") else 503
    return web.json_response({"state": state}, status=status)


async def metrics(request: Request) -> Response:
    worker = request.app[WORKER_KEY]
    # Example Prometheus metrics
    lines = [
        f'worker_state{{worker_id="{worker.worker_id}"}} {worker.get_state().value}',
        f"worker_backoff_seconds {worker._backoff}",
    ]
    return web.Response(text="\n".join(lines), content_type="text/plain")


async def start_http_server(worker: "Worker", port: int = 9200) -> None:
    app = web.Application()
    app[WORKER_KEY] = worker
    app.router.add_get("/health", health)
    app.router.add_get("/metrics", metrics)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    # Keep running forever (this task never returns)
    while True:
        await asyncio.sleep(3600)
