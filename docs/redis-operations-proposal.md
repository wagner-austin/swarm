# Redis Operations: Low-Overhead Hardening Proposal

## Summary
- Keep the current architecture (registries + typed Redis wrappers + Lua helpers).
- Prevent drift and improve clarity with a small, focused set of changes:
  - Add a single source of truth for Redis key formats (`redis_keys.py`).
  - Add a lightweight guard to flag hard‑coded key prefixes outside approved modules.
  - Document key contracts and TTL semantics.
  - Optional: add tiny helpers for health snapshot I/O (not a new service layer).

## Rationale
- The codebase already uses strict typing, Protocol‑based clients, and centralized Lua helpers.
- SessionRegistry, WorkerRegistry, BrowserHealthMonitor, and autoscaler already act as domain services.
- A separate “services” layer would duplicate existing roles and add indirection without reducing complexity.

## What Stays As‑Is (Works Well Today)
- Type safety: no `Any`, no `cast`, TypedDicts and Protocols throughout.
- Redis wrappers: `swarm/infra/redis_protocols.py` normalize types + define strict contracts.
- Batch/server‑side ops: `swarm/infra/redis_lua.py` (TTL flags, TTL scan + count, LLEN sum).
- Domain logic:
  - Affinity: `swarm/distributed/session_registry.py` (owner set/get/clear, TTL)
  - Routing: `swarm/distributed/browser_router.py`
  - Worker store: `swarm/distributed/worker_registry.py` (static cache, SCAN)
  - Health: `swarm/plugins/monitor/browser_health.py` (TTL via Lua) and `swarm/health/__main__.py` (TTL)
  - Autoscaler: `scripts/celery_autoscaler.py` (Lua LLEN sum)

## Proposed Changes

### 1) Key Contract Module (single source of truth)
- File: `swarm/infra/redis_keys.py`
- Contents (strict typing, no runtime deps):
  - Constants (Final):
    - `AFFINITY_PREFIX = "browser:affinity:"`
    - `HEARTBEAT_PREFIX = "worker:heartbeat:browser:"`
    - `HEALTH_KEY = "browser:health"`
    - `WORKER_PREFIX = "browser:worker:"`
    - `WORKER_SESSIONS_PREFIX = "browser:worker_sessions:"`
    - `SESSION_PREFIX = "browser:session:"`
  - Builders:
    - `def affinity_key(session_id: str) -> str`
    - `def heartbeat_key(worker_id: str) -> str`
    - `def worker_key(worker_id: str) -> str`
    - `def worker_sessions_key(worker_id: str) -> str`
    - `def session_key(session_id: str) -> str`
- Refactors (mechanical): replace string interpolation with builders in:
  - `swarm/distributed/session_registry.py` (affinity, worker_sessions)
  - `swarm/distributed/browser_router.py` (affinity, heartbeat)
  - `swarm/distributed/worker_lifecycle.py` (worker, worker_sessions, heartbeat)
  - `swarm/distributed/worker_registry.py` (worker, worker_sessions, heartbeat, affinity)
  - `swarm/tasks/browser.py` (session state storage)
  - `swarm/health/__main__.py` (heartbeat check)
  - `swarm/plugins/monitor/browser_health.py` + `swarm/plugins/commands/web.py` (use `HEALTH_KEY`)

### 2) Guard Against Key Drift
- Extend an existing guard to flag hard‑coded key prefixes outside approved modules.
- Approved modules (configurable):
  - `swarm/infra/redis_protocols.py`, `swarm/infra/redis_lua.py`, `swarm/infra/redis_keys.py`
  - `swarm/distributed/session_registry.py`, `swarm/distributed/worker_registry.py`, `swarm/distributed/browser_router.py`, `swarm/distributed/worker_lifecycle.py`
  - `swarm/tasks/browser.py`
  - `swarm/health/__main__.py`
  - `swarm/plugins/monitor/browser_health.py`, `swarm/plugins/commands/web.py`
  - `scripts/celery_autoscaler.py`
- Rule: occurrences of `"browser:affinity:"`, `"worker:heartbeat:browser:"`, `"browser:health"`, `"browser:worker:"`, `"browser:worker_sessions:"`, `"browser:session:"` in other modules fail lint. Builders must be used instead.
- Wire into `make lint` (non‑blocking to dev speed) alongside ruff/mypy.

### 3) Document Redis Contracts
- File: `docs/redis-operations.md`
- Contents:
  - Key contracts (owners, readers, TTLs, fields):
    - Affinity (`browser:affinity:{session_id}`) – Hash, fields per `AffinityRecord` (SessionRegistry), TTL 3600s
    - Heartbeat (`worker:heartbeat:browser:{id}`) – TTL is liveness, positive means live
    - Worker registry (`browser:worker:{id}`) – Hash, static metadata + status
    - Worker sessions (`browser:worker_sessions:{id}`) – Set of session IDs owned by worker
    - Session state (`browser:session:{session_id}`) – Hash, transient task state (e.g., current URL)
    - Health snapshot (`browser:health`) – Hash: `healthy_workers`, `is_degraded`, `last_check`, `min_required`
  - Lua helpers: what they do and when to use
  - Liveness policy: TTL‑only, no timestamp comparisons
  - Command minimization: prefer batch ops (Lua) and SCAN over KEYS

### 4) Optional: Health Snapshot Helpers
- Keep logic local to `browser_health.py` (no new service):
  - `async def write_health_snapshot(redis: RedisAsyncProtocol, status: BrowserHealthStatus) -> None`
  - `async def read_health_snapshot(redis: RedisAsyncProtocol) -> BrowserHealthStatus | None`
- Use `HEALTH_KEY` constant; normalize return types; no casts.

## Rollout Plan
- Phase 1 (docs + guard + keys):
  - Add `redis_keys.py` and `docs/redis-operations.md`.
  - Wire the guard into `make lint`.
  - Replace literals with builders in the listed modules.
- Phase 2 (polish):
  - Add snapshot helpers in `browser_health.py` and use them locally.
  - Sweep tests to use builders where literal keys appear in expectations (tests are exempt from the lint guard for readability, but should still use builders for consistency).

## Success Criteria
- Lint/CI fails if new code introduces hard‑coded Redis key prefixes.
- All Redis key construction uses builders from `redis_keys.py`.
- No behavioral regressions (TTL liveness, affinity, queue depth unchanged).
- Team can answer “who owns this key?” by opening `docs/redis-operations.md`.

## Non‑Goals
- No new generic “service layer” around Redis (avoids indirection and duplication of registries).
- No behavioral changes to queues, heartbeats, or affinity logic.

## Risks & Mitigations
- Risk: Developers forget builders and hard‑code keys.
  - Mitigation: Guard in lint + fast failure with clear guidance.
- Risk: Perceived overhead of importing builders for simple code.
  - Mitigation: Builders are trivial functions with zero runtime cost; clarity outweighs any inconvenience.

## Appendix: Current Key Contracts (for reference)
- Affinity: `browser:affinity:{session_id}` – Hash fields: `worker_id`, `direct_queue`, `timestamp`; TTL=3600s.
- Heartbeat: `worker:heartbeat:browser:{worker_id}` – TTL>0 means live; value content is not read.
- Worker registry: `browser:worker:{worker_id}` – Hash with static metadata and status/heartbeat timestamps (for UI only).
- Worker sessions: `browser:worker_sessions:{worker_id}` – Set tracking which sessions are owned by this worker.
- Session state: `browser:session:{session_id}` – Hash storing transient task state (e.g., `url` field).
- Health snapshot: `browser:health` – Hash of aggregate health fields.

