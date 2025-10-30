# Redis Operations: Key Contracts and Semantics

This document is the single source of truth for Redis key formats, ownership, TTL semantics, and how the codebase interacts with them.

## Liveness Policy
- Liveness is determined strictly by TTL on standardized heartbeat keys.
- A worker is live iff `TTL(worker:heartbeat:browser:{worker_id}) > 0`.
- No timestamp comparisons are used for liveness decisions.

## Key Contracts

### Affinity: `browser:affinity:{session_id}`
- Type: Hash
- Owner: `SessionRegistry` (set_owner, get_session_owner, clear_owner)
- Readers: `BrowserSessionRouter`
- TTL: 3600 seconds (refreshed on reads when below 50%)
- Fields (TypedDict `AffinityRecord`):
  - `worker_id: str`
  - `direct_queue: str`
  - `timestamp: str` (diagnostic; not used for liveness)

### Heartbeat: `worker:heartbeat:browser:{worker_id}`
- Type: Key with TTL (hash contents not evaluated for liveness)
- Owner: `WorkerLifecycle`
- Readers: `BrowserSessionRouter`, `SessionRegistry.find_orphaned_sessions_sync`, `BrowserHealthMonitor`, `health/__main__.py`
- TTL Policy: TTL>0 → live

### Worker Registry: `browser:worker:{worker_id}`
- Type: Hash
- Owner: `WorkerLifecycle`
- Readers: `WorkerRegistry`
- Fields: static metadata (`hostname`, `capabilities`, `platform`, etc.) and status (`current_sessions`, `last_heartbeat` for UI)

### Worker Sessions Set: `browser:worker_sessions:{worker_id}`
- Type: Set of session IDs owned by the worker
- Owner: `WorkerLifecycle` (maintained during heartbeat)
- Readers: `WorkerRegistry.get_worker_load`

### Session State: `browser:session:{session_id}`
- Type: Hash (transient task state)
- Owner: `tasks/browser.py` (e.g., current `url`)
- Readers: `tasks/browser.py` (status lookups)

### Health Snapshot: `browser:health`
- Type: Hash (aggregate health)
- Owner: `BrowserHealthMonitor` (writes)
- Readers: `plugins/commands/web.py` (reads), fallbacks when monitor not loaded
- Fields:
  - `healthy_workers: str`
  - `is_degraded: str` ("true"/"false")
  - `last_check: str` (unix seconds)
  - `min_required: str`

## Batch Operations (Lua)
- `count_ttl_healthy_by_scan(redis, pattern, scan_count) -> int`
  - Counts live heartbeat keys server‑side using SCAN + TTL.
- `ttl_flags_for_keys_sync(client, keys) -> list[int]`
  - Returns liveness flags for many heartbeat keys in a single EVAL.
- `sum_llen_via_eval(client, keys) -> int`
  - Sums LLEN across multiple lists (Celery Redis transport) in a single EVAL.

## Approved Call Sites (Direct Redis Ops)
- Infra: `swarm/infra/redis_protocols.py`, `swarm/infra/redis_lua.py`, `swarm/infra/redis_keys.py`
- Domain:
  - `swarm/distributed/session_registry.py`
  - `swarm/distributed/browser_router.py`
  - `swarm/distributed/worker_registry.py`
  - `swarm/distributed/worker_lifecycle.py`
  - `swarm/plugins/monitor/browser_health.py`
  - `swarm/plugins/commands/web.py`
  - `scripts/celery_autoscaler.py`
- Tests are exempt from lint but should use the key builders for consistency where easy.

## Notes
- Prefer SCAN over KEYS in production code; `WorkerRegistry` uses `scan_iter`.
- Prefer HGETALL over multiple HGETs when reading multiple fields.
- Use Lua helpers for batch/aggregate operations to minimize round‑trips.

