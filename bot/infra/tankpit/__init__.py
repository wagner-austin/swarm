"""TankPit infrastructure package.

Exposes :func:`engine_factory` that the DI container wires into
:class:`bot.netproxy.service.ProxyService` so the proxy remains game-agnostic.
"""

from __future__ import annotations

import asyncio

from bot.infra.tankpit.engine import TankPitEngine

__all__: list[str] = ["engine_factory"]


def engine_factory(
    q_in: "asyncio.Queue[tuple[str, bytes]]",
    q_out: "asyncio.Queue[bytes]",
) -> TankPitEngine:
    """Return a :class:`TankPitEngine` bound to the given queues."""
    return TankPitEngine(q_in, q_out)
