"""
Generic MITM-TLS proxy service.
=====================
Start/stop a TLS-MITM proxy on localhost:*port*.

* `in_q`   – every frame (dir, bytes) → state tracker / logger / AI
* `out_q`  – crafted frames from AI → server
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import (
    Any,
    Protocol,
    cast,
    runtime_checkable,
)

from mitmproxy import options, proxy
from mitmproxy.http import HTTPFlow  # For WebSocket flow type hint
from mitmproxy.tools.dump import DumpMaster

from bot.core.service_base import ServiceABC
from bot.core.settings import settings
from bot.core.telemetry import update_queue_gauge

# Removed: from .addon import WSAddon

logger = logging.getLogger(__name__)


@runtime_checkable
class AddonProtocol(Protocol):  # minimal contract
    async def websocket_message(self, flow: HTTPFlow) -> None: ...


class ProxyService(ServiceABC):
    def __init__(
        self,
        port: int = 9000,
        *,
        certdir: Path | None = None,
        addons: list[AddonProtocol] | None = None,
    ):
        self._default_port = port
        self.port = port
        self.certdir = certdir or Path(".mitm_certs")
        # Bounded queues prevent unbounded memory growth under heavy load.
        # Tuned based on typical traffic patterns: inbound frames larger and
        # more frequent than outbound AI-crafted frames.
        self.in_q: asyncio.Queue[tuple[str, bytes]] = asyncio.Queue(maxsize=settings.queues.inbound)
        self.out_q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=settings.queues.outbound)
        # initialise gauges
        update_queue_gauge("proxy_in", self.in_q)
        update_queue_gauge("proxy_out", self.out_q)
        self._dump: DumpMaster | None = None
        self._task: asyncio.Future[None] | None = None
        self._addons: list[AddonProtocol] = addons or []
        self._process: asyncio.subprocess.Process | None = None

    # ── public API ──────────────────────────────────────────────
    async def start(self) -> None:
        if self._dump:
            return
        # Always delegate to utils.net – single source of truth
        from bot.utils.net import pick_free_port

        self.port = await pick_free_port(self.port)

        opts = options.Options(
            listen_host="127.0.0.1",
            listen_port=self.port,
            confdir=str(self.certdir),
        )
        # Ignore *all* loop-back traffic so any localhost service bypasses the proxy.
        LOOPBACK_RE: str = r"^(localhost|127\.0\.0\.1)(:\d+)?$"
        cast(Any, opts).update(ignore_hosts=[LOOPBACK_RE])

        ProxyConfig: Any | None = getattr(proxy, "ProxyConfig", None)
        ProxyServer: Any | None = getattr(proxy, "ProxyServer", None)
        # Disable mitmproxy’s built-in "termlog" and "dumper" handlers to
        # prevent duplicate log lines once our own logging is configured.
        # Both flags default to True; overriding keeps proxy functionality but
        # stops extra StreamHandlers from being attached to the root logger.
        self._dump = DumpMaster(opts, with_termlog=False, with_dumper=False)

        # mitmproxy <9 needs explicit server objects
        if ProxyConfig is not None and ProxyServer is not None:
            pconf = ProxyConfig(opts)
            # .server is missing in type stubs
            cast(Any, self._dump).server = ProxyServer(pconf)
        # mitmproxy 9/10: DumpMaster listens automatically
        # wire addons
        for addon in self._addons:
            instance = addon(self.in_q, self.out_q) if isinstance(addon, type) else addon
            self._dump.addons.add(instance)  # type: ignore[no-untyped-call]
        # Ensure the certdir exists
        self.certdir.mkdir(parents=True, exist_ok=True)
        # run mitmproxy in the background
        try:
            self._task = asyncio.create_task(self._dump.run())  # spawn the coroutine
            await asyncio.sleep(0)  # let it start; surfaces import errors fast
            logger.info(
                f"ProxyService: mitmproxy task created, listening on http://127.0.0.1:{self.port}"
            )
        except Exception:
            self._task = None  # Ensure task is None if startup fails
            if self._dump:  # Check if dump was initialized
                self._dump.shutdown()  # type: ignore[no-untyped-call] # Attempt to shutdown dump master
            raise  # Re-raise the exception so the caller knows startup failed
        return

    # _pick_free_port and _is_port_free are now in bot.utils.net

    async def stop(self, *, graceful: bool = True) -> None:
        # Check if proxy was never started
        if not self._dump and not self._task:
            return

        # Check if proxy is not running but may have been started before
        if not self._dump:
            logger.info("ProxyService: No active mitmproxy instance to stop.")
            self._task = None
            self.port = self._default_port
            return

        logger.info("ProxyService: Shutting down mitmproxy.")
        assert self._dump is not None  # Ensured by the checks above
        self._dump.shutdown()  # type: ignore[no-untyped-call] # tell mitmproxy to stop
        if self._task:
            if not self._task.done():  # Only operate on tasks that aren't done
                self._task.cancel()
                try:
                    # wait up to 3 s so the OS definitely releases the socket
                    await asyncio.wait_for(self._task, timeout=3)
                except asyncio.CancelledError:
                    logger.info("ProxyService: mitmproxy task cancelled as expected.")
                    # pass # Expected, no specific action needed beyond logging
                except Exception as e:  # Catch other errors during await
                    logger.error(
                        f"ProxyService: Error awaiting mitmproxy task after cancellation: {e}"
                    )
            elif self._task.exception():  # If task is done and has an exception, log it
                try:
                    self._task.result()  # This will re-raise the exception
                except Exception as e:
                    logger.error(
                        f"ProxyService: mitmproxy task had already finished with an error: {e}"
                    )
            # If task is done without exception, it's fine.

        # Clean up instance variables
        self._dump = None
        self._task = None
        # reset to the *original* preferred port so the next call to start()
        # tries the same number first (nice for humans, harmless for tests).
        self.port = self._default_port
        logger.info("ProxyService: mitmproxy stopped.")

    # convenience helper for unit tests
    def is_running(self) -> bool:
        return self._dump is not None

    # ------------------------------------------------------------------+
    # Human-readable status string                                      |
    # ------------------------------------------------------------------+

    def describe(self) -> str:
        """
        Quick snapshot for Discord:

        • state (running / stopped)
        • bind address
        • queue sizes – tells the user if frames are piling up
        """
        if not self.is_running():
            return "stopped"

        in_q_len: int = self.in_q.qsize()
        out_q_len: int = self.out_q.qsize()
        return (
            f"running on http://127.0.0.1:{self.port} — "
            f"{in_q_len} inbound / {out_q_len} outbound frames queued"
        )

    async def aclose(self) -> None:
        """Gracefully stop the mitmproxy service.
        This method ensures that the existing stop() logic is awaited.
        """
        logger.info("ProxyService: aclose() called. Initiating shutdown via stop().")
        await self.stop()

        logger.info("ProxyService: aclose() completed.")


# ------------------------------------------------------------------
# module‑level singleton so other modules can just "from … import proxy_service"
# ------------------------------------------------------------------

proxy_service: ProxyService = ProxyService()
