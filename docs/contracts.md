# System Contracts

This document captures the authoritative contracts for health, routing, typing, and testing across the codebase.

## Health & Liveness
- Worker health derives exclusively from Redis heartbeats using a freshness rule; no control‑plane calls (e.g., Celery Inspect) in decision loops.
- Health endpoints:
  - Swarm main: `http://localhost:9200/metrics`
  - Workers: `http://localhost:9100/metrics`

## Session Affinity
- Session affinity is stored as a Redis hash under `browser:affinity:{session_id}` with fields:
  - `worker_id`: canonical worker id (host‑only)
  - `direct_queue`: per‑worker direct queue name (e.g., `browser.direct.{worker_id}`)
  - `timestamp`: ISO timestamp of last write (optional)
- Consumers do not derive queue names; they consult the registry/router.

## Task Runtime & Typing
- All Celery tasks return TypedDict responses defined under `swarm.browser.types`.
- Runtime tasks use a thread‑local event loop and run on the engine’s dedicated loop when required.
- Strict typing is enforced end‑to‑end (mypy --strict); casts are avoided by using Protocols and structural typing.

## Prohibited Constructs (Guarded)
- `typing.cast(...)` — forbidden in repo guards.
- `typing.Any` — forbidden in guarded paths.
- Direct Redis client construction: use `redis.from_url(...)` with wrapper (`wrap_redis_sync/async`).
- Unsafe subprocess calls in libraries: avoid `subprocess.*`, `os.system/popen`; use asyncio subprocess where appropriate.

## Redis Safety
- Local/testing must use one of:
  - Direct local test DB: `redis://localhost:6379/15`
  - HAProxy test route: `redis://haproxy-redis:6380/0`
- `scripts/guard_test_redis_safety.py` validates env and prints diagnostics.
- `scripts/guard_flushdb_runtime.install()` prevents accidental `flushdb/flushall` outside safe URLs.

## Celery Contracts
- Broker: Redis via HAProxy (`haproxy-redis:6380/0`) in tests/dev by default.
- Result expiry: one hour to prevent unbounded accumulation.
- Queue naming:
  - Base queue: `browser`
  - Per‑worker direct queues: `browser.direct.{worker_id}`

## Observability
- Metrics via Prometheus (exported by workers and celery‑exporter) and Dashboards in Grafana.
- Logs via Loki (collected by Alloy).

