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
from types import TracebackType
from typing import (
    Any,
    Callable,
    Protocol,
    cast,
    runtime_checkable,
)

from mitmproxy import options, proxy
from mitmproxy.http import HTTPFlow  # For WebSocket flow type hint
from mitmproxy.tools.dump import DumpMaster

from bot.core.service_base import ServiceABC
from bot.core.settings import settings
from bot.utils.queue_helpers import new_pair

# Removed: from .addon import WSAddon

logger = logging.getLogger(__name__)


@runtime_checkable
class AddonProtocol(Protocol):  # minimal contract
    async def websocket_message(self, flow: HTTPFlow) -> None: ...


# ------------------------------------------------------------+
#  Game-engine protocol                                       +
# ------------------------------------------------------------+


@runtime_checkable
class GameEngine(Protocol):
    async def start(self) -> None: ...

    async def stop(self, *, graceful: bool = True) -> None: ...


class ProxyService(ServiceABC):
    def __init__(
        self,
        port: int = 9000,
        *,
        certdir: Path | None = None,
        addons: list[AddonProtocol] | None = None,
        engine_factory: Callable[
            [asyncio.Queue[tuple[str, bytes]], asyncio.Queue[bytes]], GameEngine
        ]
        | None = None,
        queue_pair_fn: Callable[[str], tuple[asyncio.Queue[Any], asyncio.Queue[Any]]] = new_pair,
        pick_free_port_fn: Callable[[int], Any] | None = None,
        create_task_fn: Callable[[Any], asyncio.Task[Any]] = asyncio.create_task,
        sleep_fn: Callable[[float], Any] = asyncio.sleep,
        dump_master_factory: Callable[[Any], Any] | None = None,
        logger: logging.Logger | None = None,
        subprocess_factory: Callable[..., Any] | None = None,
    ):
        self._default_port = port
        self.port = port
        self.certdir = certdir or Path(".mitm_certs")
        # Centralised helper returns bounded queues sized per settings.queues
        self.in_q, self.out_q = queue_pair_fn("proxy")

        # Injected helpers for testability
        if pick_free_port_fn is None:
            from bot.utils.net import pick_free_port as _pick_free_port

            pick_free_port_fn = _pick_free_port
        if dump_master_factory is None:

            def dump_master_factory(opts: Any) -> DumpMaster:
                return DumpMaster(opts, with_termlog=False, with_dumper=False)

        self._pick_free_port_fn = pick_free_port_fn
        self._create_task_fn = create_task_fn
        self._sleep_fn = sleep_fn
        self._dump_master_factory: Callable[[Any], Any] = dump_master_factory

        # Dependency-injected logger and subprocess factory
        self._logger: logging.Logger = logger or logging.getLogger(__name__)
        if subprocess_factory is None:
            import asyncio

            subprocess_factory = asyncio.create_subprocess_exec
        self._subprocess_factory = subprocess_factory

        self._dump: DumpMaster | None = None
        self._task: asyncio.Future[None] | None = None
        self._addons: list[AddonProtocol] = addons or []
        # ------------------------------------------------------------------+
        # Build the game engine                                            +
        # ------------------------------------------------------------------+
        if engine_factory is None:
            from bot.infra.tankpit.engine import TankPitEngine

            engine_factory = lambda q_in, q_out: TankPitEngine(q_in, q_out)  # noqa: E731

        self._engine: GameEngine = engine_factory(self.in_q, self.out_q)
        self._process: asyncio.subprocess.Process | None = None

    # ── public API ──────────────────────────────────────────────
    async def start(self) -> None:
        if self._dump:
            return
        # Pick a free port via injected helper
        self.port = await self._pick_free_port_fn(self.port)

        opts = options.Options(
            listen_host="127.0.0.1",
            listen_port=self.port,
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

        # ------------------------------------------------------------------
        # Create DumpMaster – factory may be sync or async
        # ------------------------------------------------------------------
        try:
            dump_candidate = self._dump_master_factory(opts)
            if asyncio.iscoroutine(dump_candidate):
                dump_candidate = await dump_candidate
            self._dump = dump_candidate
        except Exception:
            # If factory fails, ensure state is clean before propagating
            self._dump = None
            raise

        # mitmproxy <9 needs explicit server objects
        if ProxyConfig is not None and ProxyServer is not None:
            pconf = ProxyConfig(opts)
            cast(Any, self._dump).server = ProxyServer(pconf)

        for addon in self._addons:
            instance = addon(self.in_q, self.out_q) if isinstance(addon, type) else addon
            self._dump.addons.add(instance)
        # Kick-off the game engine
        await self._engine.start()

        # Ensure the certdir exists
        self.certdir.mkdir(parents=True, exist_ok=True)
        # run mitmproxy in the background
        run_coro = None
        task_created = False
        try:
            run_coro = self._dump.run()  # create coroutine object
            self._task = self._create_task_fn(run_coro)  # schedule task
            task_created = True
            await self._sleep_fn(0)  # let it start; surfaces import errors fast
            logger.info(
                f"ProxyService: mitmproxy task created, listening on http://127.0.0.1:{self.port}"
            )
        except Exception:
            # ------------------------------------------------------------------
            # Roll-back on *any* failure during startup so tests see clean state
            # ------------------------------------------------------------------
            if self._task and not self._task.done():
                self._task.cancel()
            self._task = None

            # Close the coroutine to suppress "never awaited" warnings
            if run_coro is not None:
                try:
                    run_coro.close()
                except Exception:
                    pass

            # Only shutdown dump if task was successfully created and might be running
            if self._dump is not None and task_created:
                try:
                    self._dump.shutdown()
                except Exception:
                    pass
            # Always clear dump on failure since service is not running
            self._dump = None

            # Reset port so subsequent starts reuse the preferred port
            self.port = self._default_port
            raise  # Propagate to caller so they can handle failure
        return

    # _pick_free_port and _is_port_free are now in bot.utils.net

    async def stop(self, *, graceful: bool = True) -> None:
        # Check if proxy was never started – still stop engine if running
        if not self._dump and not self._task:
            await self._engine.stop()
            return

        # Check if proxy is not running but may have been started before
        if not self._dump:
            self._logger.info("ProxyService: No active mitmproxy instance to stop.")
            self._task = None
            self.port = self._default_port
            return

        self._logger.info("ProxyService: Shutting down mitmproxy.")
        assert self._dump is not None  # Ensured by the checks above
        self._dump.shutdown()  # type: ignore[no-untyped-call] # tell mitmproxy to stop
        if self._task:
            if not self._task.done():  # Only operate on tasks that aren't done
                self._task.cancel()
                try:
                    # wait up to 3 s so the OS definitely releases the socket
                    await asyncio.wait_for(self._task, timeout=3)
                except asyncio.CancelledError:
                    self._logger.info("ProxyService: mitmproxy task cancelled as expected.")
                    # pass # Expected, no specific action needed beyond logging
                except Exception as e:  # Catch other errors during await
                    self._logger.error(
                        f"ProxyService: Error awaiting mitmproxy task after cancellation: {e}"
                    )
            elif self._task.exception():  # If task is done and has an exception, log it
                try:
                    self._task.result()  # This will re-raise the exception
                except Exception as e:
                    self._logger.error(
                        f"ProxyService: mitmproxy task had already finished with an error: {e}"
                    )
            # If task is done without exception, it's fine.

        # Clean up instance variables
        self._dump = None
        self._task = None
        # reset to the *original* preferred port so the next call to start()
        # tries the same number first (nice for humans, harmless for tests).
        self.port = self._default_port
        self._logger.info("ProxyService: mitmproxy stopped.")

        # Stop game engine
        try:
            await self._engine.stop()
        except Exception as exc:
            self._logger.warning("ProxyService: engine stop raised %s", exc)

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
        self._logger.info("ProxyService: aclose() called. Initiating shutdown via stop().")
        await self.stop()

        self._logger.info("ProxyService: aclose() completed.")


# ------------------------------------------------------------------
# module‑level singleton so other modules can just "from … import proxy_service"
# ------------------------------------------------------------------

proxy_service: ProxyService = ProxyService()
