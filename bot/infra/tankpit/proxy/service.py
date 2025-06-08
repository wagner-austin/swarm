"""
tankpit.proxy.service
=====================
Start/stop a TLS-MITM proxy on localhost:*port*.

* `in_q`   – every frame (dir, bytes) → state tracker / logger / AI
* `out_q`  – crafted frames from AI → server
"""

from __future__ import annotations
import asyncio
import logging
from pathlib import Path
from mitmproxy import options, proxy
from typing import Any, cast
from mitmproxy.tools.dump import DumpMaster
from .addon import WSAddon

log = logging.getLogger(__name__)


class ProxyService:
    def __init__(self, port: int = 9000, certdir: Path | None = None):
        self.port = port
        self.certdir = certdir or Path(".mitm_certs")
        self.in_q: asyncio.Queue[tuple[str, bytes]] = asyncio.Queue()
        self.out_q: asyncio.Queue[bytes] = asyncio.Queue()
        self._dump: DumpMaster | None = None
        self._task: asyncio.Future[None] | None = (
            None  # run_in_executor returns a Future
        )

    # ── public API ──────────────────────────────────────────────
    async def start(self) -> str:
        if self._dump:
            return f"Proxy already running on :{self.port}"
        opts = options.Options(
            listen_host="127.0.0.1", listen_port=self.port, confdir=str(self.certdir)
        )

        # ── older wheels (<9) expose these; v9+ do not ────────────────────
        ProxyConfig: Any | None = getattr(proxy, "ProxyConfig", None)
        ProxyServer: Any | None = getattr(proxy, "ProxyServer", None)
        # ------------------------------------------------------------------

        self._dump = DumpMaster(opts)

        # mitmproxy <9 needs explicit server objects
        if ProxyConfig is not None and ProxyServer is not None:
            pconf = ProxyConfig(opts)
            # .server is missing in type stubs
            cast(Any, self._dump).server = ProxyServer(pconf)
        # mitmproxy 9/10: DumpMaster listens automatically
        # wire the addon
        self._dump.addons.add(WSAddon(self.in_q, self.out_q))  # type: ignore[no-untyped-call]
        # Ensure the certdir exists
        self.certdir.mkdir(parents=True, exist_ok=True)
        # run mitmproxy in the background
        try:
            self._task = asyncio.create_task(self._dump.run())  # spawn the coroutine
            await asyncio.sleep(0)  # let it start; surfaces import errors fast
            log.info(
                f"ProxyService: mitmproxy task created, listening on http://127.0.0.1:{self.port}"
            )
        except Exception:
            self._task = None  # Ensure task is None if startup fails
            if self._dump:  # Check if dump was initialized
                self._dump.shutdown()  # type: ignore[no-untyped-call] # Attempt to shutdown dump master
            raise  # Re-raise the exception so the caller knows startup failed
        return f"Proxy listening on http://127.0.0.1:{self.port}"

    async def stop(self) -> str:
        if not self._dump:
            return "Proxy not running."
        log.info("ProxyService: Shutting down mitmproxy.")
        assert self._dump is not None  # Ensured by the 'if not self._dump:' check above
        self._dump.shutdown()  # type: ignore[no-untyped-call] # tell mitmproxy to stop
        if self._task:
            if not self._task.done():  # Only operate on tasks that aren't done
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    log.info("ProxyService: mitmproxy task cancelled as expected.")
                    # pass # Expected, no specific action needed beyond logging
                except Exception as e:  # Catch other errors during await
                    log.error(
                        f"ProxyService: Error awaiting mitmproxy task after cancellation: {e}"
                    )
            elif self._task.exception():  # If task is done and has an exception, log it
                try:
                    self._task.result()  # This will re-raise the exception
                except Exception as e:
                    log.error(
                        f"ProxyService: mitmproxy task had already finished with an error: {e}"
                    )
            # If task is done without exception, it's fine.

        # Clean up instance variables
        self._dump = None
        self._task = None
        log.info("ProxyService: mitmproxy stopped.")
        return "Proxy stopped."

    # convenience helper for unit tests
    def is_running(self) -> bool:
        return self._dump is not None
