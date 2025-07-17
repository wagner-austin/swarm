"""Unit tests for swarm.core.metrics helper functions.

Ensures the public helpers increment *swarmh* the in-memory integer counter and
underlying Prometheus counter.
"""

from __future__ import annotations

from typing import Any

from swarm.core import metrics
from swarm.core.telemetry import DISCORD_MSG_TOTAL, SWARM_MSG_TOTAL


def _read_prom_counter(counter: Any) -> float:
    """Return the current float value of a ``prometheus_client.Counter``."""
    return float(getattr(counter, "_value").get())


class TestMetricHelpers:
    """Smoke-tests for public increment helpers."""

    def test_increment_message_count(self) -> None:
        # Snapshot before
        start_int = metrics.messages_sent
        start_prom = _read_prom_counter(SWARM_MSG_TOTAL)

        metrics.increment_message_count()

        assert metrics.messages_sent == start_int + 1
        assert _read_prom_counter(SWARM_MSG_TOTAL) == start_prom + 1.0

    def test_increment_discord_message_count(self) -> None:
        start_int = metrics.discord_messages_processed
        start_prom = _read_prom_counter(DISCORD_MSG_TOTAL)

        metrics.increment_discord_message_count()

        assert metrics.discord_messages_processed == start_int + 1
        assert _read_prom_counter(DISCORD_MSG_TOTAL) == start_prom + 1.0
