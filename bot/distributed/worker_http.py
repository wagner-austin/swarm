"""
HTTP server for worker health and metrics endpoints.
Exposes /health (JSON) and /metrics (Prometheus text format).
"""

import asyncio
from typing import TYPE_CHECKING

from aiohttp import web

if TYPE_CHECKING:
    from .worker import Worker


async def health(request: web.Request) -> web.Response:
    worker: Worker = request.app["worker"]
    state = worker.get_state().name
    status = 200 if state not in ("ERROR", "SHUTDOWN") else 503
    return web.json_response({"state": state}, status=status)


async def metrics(request: web.Request) -> web.Response:
    worker: Worker = request.app["worker"]
    # Example Prometheus metrics
    lines = [
        f'worker_state{{worker_id="{worker.worker_id}"}} {worker.get_state().value}',
        f"worker_backoff_seconds {worker._backoff}",
    ]
    return web.Response(text="\n".join(lines), content_type="text/plain")


async def start_http_server(worker: "Worker", port: int = 9200) -> None:
    app = web.Application()
    app["worker"] = worker
    app.router.add_get("/health", health)
    app.router.add_get("/metrics", metrics)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    # Keep running forever (this task never returns)
    while True:
        await asyncio.sleep(3600)
