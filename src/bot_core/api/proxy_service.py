"""
ProxyService – TLS MITM stub
---------------------------------
This is just the skeleton so other modules can import it.
A real implementation arrives in step 2.
"""

from __future__ import annotations
import asyncio
import logging

log = logging.getLogger(__name__)


class ProxyService:
    def __init__(self, port: int = 9000) -> None:
        self.port = port
        self.in_q: asyncio.Queue[bytes] = asyncio.Queue()
        self.out_q: asyncio.Queue[bytes] = asyncio.Queue()
        self._server_task: asyncio.Task[None] | None = None

    async def start(self) -> str:
        # real MITM code will appear later
        log.info("[Proxy] (stub) start called")
        return "Proxy stub started (does nothing yet)."

    async def stop(self) -> str:
        log.info("[Proxy] (stub) stop called")
        return "Proxy stub stopped."


# convenience singleton
default_proxy_service = ProxyService()
