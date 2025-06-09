"""
tankpit.proxy.addon
===================
A mitmproxy *addon* that pushes WS frames into async Queues.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from mitmproxy import ctx, websocket

# ── type-only import; mitmproxy stubs are incomplete ───────────────
if TYPE_CHECKING:
    from mitmproxy.http import HTTPFlow

# mitmproxy's opcode enum (TEXT=1, BINARY=2, …) – we need just the binary value
OP_BINARY = 0x2
# -------------------------------------------------------------------


class TankPitWSAddon:  # Renamed from WSAddon
    def __init__(
        self, inbound: asyncio.Queue[tuple[str, bytes]], outbound: asyncio.Queue[bytes]
    ) -> None:
        self.in_q = inbound
        self.out_q = outbound

    # called whenever a WS frame passes the proxy
    async def websocket_message(self, flow: HTTPFlow) -> None:
        if not flow.websocket:
            return
        msg = flow.websocket.messages[-1]
        direction = "TX" if msg.from_client else "RX"
        await self.in_q.put((direction, msg.content))

    # we also tick every 50 ms to flush bot frames → upstream
    async def running(self) -> None:
        """Periodically called by mitmproxy to allow background tasks.
        Here, we take crafted frames from out_q and inject them server-bound.
        """
        while True:
            data = await self.out_q.get()
            try:
                # The ctx.master.state access might still flag in MyPy if stubs are incomplete,
                # but this is standard mitmproxy addon practice.
                if ctx.master and hasattr(
                    ctx.master, "state"
                ):  # Check for state to be safe
                    for f_flow in ctx.master.state.flows:  # Iterate all flows
                        if f_flow.websocket and not f_flow.websocket.closed:
                            # Assuming TankPit uses binary frames for game data.
                            # websocket.OPCODE.BINARY is typically 0x2.
                            # If text frames are used, it should be websocket.OPCODE.TEXT (0x1).
                            new_msg = websocket.WebSocketMessage(
                                OP_BINARY,  # ← replaces websocket.OPCODE_BINARY
                                from_client=True,
                                content=data,
                            )
                            f_flow.websocket.messages.append(new_msg)
                            # The original spec included f_flow.websocket.send().
                            # This sends the last message in the queue, or a specific message if passed as arg.
                            # It's often sufficient to just append, but we'll follow the spec.
                            if hasattr(
                                f_flow.websocket, "send_message"
                            ):  # mitmproxy 6+ uses send_message
                                f_flow.websocket.send_message(new_msg)
                            elif hasattr(
                                f_flow.websocket, "send"
                            ):  # Older versions might use send directly with a message obj
                                f_flow.websocket.send(new_msg)
            except Exception as e:
                # It's good to log errors in a background task like this
                if hasattr(ctx, "log") and hasattr(ctx.log, "error"):
                    ctx.log.error(f"Error in TankPitWSAddon running loop: {e}")  # type: ignore[no-untyped-call]
            finally:
                self.out_q.task_done()
