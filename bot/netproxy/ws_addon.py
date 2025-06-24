"""Generic WebSocket MITM-proxy add-on.

This add-on is responsible for two things:

1.  Push every binary WebSocket frame that traverses the proxy into an
    *inbound* queue so that game-specific engines, loggers or AIs can process
    them in an asyncio context.
2.  Pull crafted frames from an *outbound* queue and inject them into *all*
    open WebSocket connections so they are forwarded upstream to the game
    server.

The implementation purposefully contains *no* game-specific logic; it only
concerns itself with frame transport so that any engine can be attached by
wiring the same pair of queues.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from mitmproxy import ctx, websocket

if TYPE_CHECKING:  # mitmproxy type stubs are incomplete
    from mitmproxy.http import HTTPFlow


class GenericWSAddon:
    """A generic MITM-proxy WebSocket dispatcher."""

    def __init__(
        self,
        inbound: asyncio.Queue[tuple[str, bytes]],
        outbound: asyncio.Queue[bytes],
    ) -> None:
        self._in = inbound
        self._out = outbound

    # ------------------------------------------------------------------+
    # mitmproxy hooks                                                   +
    # ------------------------------------------------------------------+
    async def websocket_message(self, flow: "HTTPFlow") -> None:  # noqa: D401
        """Called by mitmproxy for **every** WebSocket message."""
        if not flow.websocket:
            return
        msg = flow.websocket.messages[-1]
        direction = "TX" if msg.from_client else "RX"
        try:
            # Fast-path; if the queue is full we emit an alert but continue.
            self._in.put_nowait((direction, msg.content))
        except asyncio.QueueFull:
            from bot.core import alerts

            alerts.alert("Proxy inbound queue overflow – dropping frame")

    async def running(self) -> None:  # noqa: D401 – mitmproxy naming convention
        """Background task that flushes the outbound queue."""
        while True:
            data = await self._out.get()
            try:
                # Iterate over *all* open WS connections and inject the frame
                for f in ctx.master.state.flows:  # type: ignore[attr-defined]
                    if f.websocket and not f.websocket.closed:
                        new_msg = websocket.WebSocketMessage(
                            opcode=websocket.Opcode.BINARY,
                            from_client=True,
                            content=data,
                        )
                        f.websocket.messages.append(new_msg)
                        # mitmproxy >= 10 only exposes send_message()
                        f.websocket.send_message(new_msg)
            finally:
                self._out.task_done()
