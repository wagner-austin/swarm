"""
Typed, dependency-optional metrics helpers for Counters and Gauges.

Provides a small, strictly-typed facade over prometheus_client without using
typing.Any or casts. If prometheus_client is unavailable, returns no-op
implementations that satisfy the same Protocols.
"""

from __future__ import annotations

from typing import Protocol


class CounterChild(Protocol):
    def inc(self, amount: float = 1.0) -> None: ...


class GaugeChild(Protocol):
    def set(self, value: float) -> None: ...


class Counter(Protocol):
    def labels(self, *, worker_id: str) -> CounterChild: ...


class Gauge(Protocol):
    def labels(self, *, worker_id: str) -> GaugeChild: ...


# -------------------------------
# No-op implementations
# -------------------------------


class _NoopCounterChild:
    def inc(self, amount: float = 1.0) -> None:
        return None


class _NoopGaugeChild:
    def set(self, value: float) -> None:
        return None


class _NoopCounter:
    def labels(self, *, worker_id: str) -> CounterChild:
        return _NoopCounterChild()


class _NoopGauge:
    def labels(self, *, worker_id: str) -> GaugeChild:
        return _NoopGaugeChild()


# -------------------------------
# Prometheus-backed implementations
# -------------------------------


class _PromCounterChild:
    def __init__(self, inner: object) -> None:
        # inner supports inc()
        self._inner = inner

    def inc(self, amount: float = 1.0) -> None:
        # Runtime attribute access, but no typing.Any usage
        getattr(self._inner, "inc")(amount)


class _PromGaugeChild:
    def __init__(self, inner: object) -> None:
        # inner supports set()
        self._inner = inner

    def set(self, value: float) -> None:
        getattr(self._inner, "set")(value)


class _PromCounter:
    def __init__(self, inner: object) -> None:
        # inner supports labels(worker_id=...) -> obj with inc()
        self._inner = inner

    def labels(self, *, worker_id: str) -> CounterChild:
        labeled = getattr(self._inner, "labels")(worker_id=worker_id)
        return _PromCounterChild(labeled)


class _PromGauge:
    def __init__(self, inner: object) -> None:
        # inner supports labels(worker_id=...) -> obj with set()
        self._inner = inner

    def labels(self, *, worker_id: str) -> GaugeChild:
        labeled = getattr(self._inner, "labels")(worker_id=worker_id)
        return _PromGaugeChild(labeled)


def make_counter(name: str, documentation: str) -> Counter:
    try:
        from prometheus_client import Counter as _PCounter

        inner = _PCounter(name, documentation, ["worker_id"])  # runtime type
        return _PromCounter(inner)
    except Exception:
        return _NoopCounter()


def make_gauge(name: str, documentation: str) -> Gauge:
    try:
        from prometheus_client import Gauge as _PGauge

        inner = _PGauge(name, documentation, ["worker_id"])  # runtime type
        return _PromGauge(inner)
    except Exception:
        return _NoopGauge()
