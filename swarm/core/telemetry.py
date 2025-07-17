"""core/telemetry.py
====================
Prometheus metrics registry and helper utilities.

This module centralises every runtime metric exposed by the Discord swarm and
hosts an in-process HTTP exporter that Prometheus can scrape.  All other
sub-systems should depend only on the light-weight helper functions defined
here – they do **not** need to import anything directly from
``prometheus_client``.

The exporter is started idempotently via :func:`start_exporter` which is called
from the lifecycle bootstrap.  If the configured port is ``0`` or the exporter
has already been started, the call becomes a no-op.
"""

from __future__ import annotations

import asyncio
import logging
import os
from errno import EADDRINUSE
from typing import Any

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    PlatformCollector,
    ProcessCollector,
    start_http_server,
)

__all__ = [
    "record_llm_call",
    "record_frame",
    "update_queue_gauge",
    "start_exporter",
]

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------+
#  Global registry                                                            +
# ---------------------------------------------------------------------------+

REGISTRY: CollectorRegistry = CollectorRegistry(auto_describe=True)

# Register default collectors for CPU, memory, platform info
ProcessCollector(registry=REGISTRY)
PlatformCollector(registry=REGISTRY)

# ——— LLM metrics ————————————————————————————————————————————————
LLM_REQUEST_TOTAL = Counter(
    "llm_request_total",
    "LLM completions by provider and status",
    ["provider", "status"],
    registry=REGISTRY,
)
LLM_LATENCY = Histogram(
    "llm_latency_seconds",
    "End-to-end LLM completion latency",
    ["provider"],
    registry=REGISTRY,
)

# ——— TankPit frame metrics ————————————————————————————————————————
FRAME_TOTAL = Counter(
    "tankpit_frame_total",
    "Binary frames processed by direction",
    ["direction"],
    registry=REGISTRY,
)
FRAME_LATENCY = Histogram(
    "tankpit_frame_latency_seconds",
    "Time spent handling one frame",
    registry=REGISTRY,
)

# ——— Dynamic gauges ————————————————————————————————————————————————
QUEUE_SIZE = Gauge(
    "swarm_queue_fill",
    "Current fill level of named asyncio.Queue",
    ["queue"],
    registry=REGISTRY,
)

# Resolve shard label once at import time so all metrics share it
_SHARD_ID: str = os.getenv("SHARD_ID", "0")

# ——— Core swarm latency ————————————————————————————————————————————
# Create a Histogram with a *dynamic* "shard" label and bind it immediately
# to a single child instance – this avoids mypy complaints about the newer
# ``const_labels`` kwarg while still exposing the label in Prometheus.
SWARM_LATENCY = Histogram(
    "swarm_latency_seconds",
    "Discord gateway latency in seconds",
    ["shard"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 5.0),
    registry=REGISTRY,
).labels(_SHARD_ID)

# ——— Swarm traffic metrics ————————————————————————————————————————————
DISCORD_MSG_TOTAL = Counter(
    "discord_messages_processed_total",
    "Discord messages the swarm has processed",
    ["shard"],
    registry=REGISTRY,
).labels(_SHARD_ID)

SWARM_MSG_TOTAL = Counter(
    "swarm_messages_sent_total",
    "Messages the swarm has sent",
    ["shard"],
    registry=REGISTRY,
).labels(_SHARD_ID)

# ---------------------------------------------------------------------------+
#  Public helpers                                                            +
# ---------------------------------------------------------------------------+


def record_llm_call(provider: str, status: str, duration_s: float) -> None:
    """Fast non-blocking metrics update for an LLM completion."""
    LLM_REQUEST_TOTAL.labels(provider, status).inc()
    LLM_LATENCY.labels(provider).observe(duration_s)


def record_frame(direction: str, duration_s: float) -> None:
    """Record one processed TankPit frame."""
    FRAME_TOTAL.labels(direction).inc()
    FRAME_LATENCY.observe(duration_s)


def update_queue_gauge(name: str, q: asyncio.Queue[Any]) -> None:
    """Export instantaneous fill level of an ``asyncio.Queue``."""
    QUEUE_SIZE.labels(name).set(q.qsize())


# ---------------------------------------------------------------------------+
#  Exporter bootstrap                                                        +
# ---------------------------------------------------------------------------+

_started: bool = False


def start_exporter(port: int) -> None:
    """Start the Prometheus HTTP exporter.

    Behaviour:
    • No-op when *port* == 0 (disabled).
    • Idempotent – subsequent calls after the first successful start() return immediately.
    • If the preferred *port* is already taken, automatically retries once on *port* + 1.
    """
    global _started
    if port == 0 or _started:
        return

    try:
        start_http_server(port, registry=REGISTRY)
        actual = port
    except OSError as exc:  # pragma: no cover – depends on environment
        if exc.errno == EADDRINUSE:
            alt = port + 1
            _log.warning("Metrics port %d in use – falling back to %d", port, alt)
            start_http_server(alt, registry=REGISTRY)
            actual = alt
        else:
            raise

    _started = True
    _log.info("📈 Prometheus exporter listening on :%s/metrics", actual)
