# Swarm Architecture & Reliability Audit

This document records a deep audit of the Swarm codebase: current architecture, what is actually wired and running, where it’s inconsistent, and a prioritized hardening plan. It focuses on task delegation, job queues, container management, state, Redis/Upstash usage, dependency injection, and logging/observability.


## Executive Summary

- The core architecture is solid: Celery for tasking, Redis via HAProxy for failover, a Docker API–driven autoscaler, and a clean session-affinity router for browser tasks.
- The largest operational risks are (1) Redis command budget (Upstash) burn from heartbeats and occasional key scans; and (2) a mismatch in the job queue/session design that prevents correct routing and scaling.
- Container orchestration exists (Docker API, K8s, Fly) but isn’t unified behind one source of truth; DI also bypasses the Redis failover abstraction in most places.
- Logging/metrics are robust and centralized.

High‑impact fixes:
- Fix the browser job flow so all browser operations use a stable `task_id` (session id) and route via the session router. Adjust autoscaler to include per‑worker direct queues in queue depth.
- Keep only one heartbeat mechanism (the Celery WorkerLifecycle), increase its interval, and purge KEYS usage in runtime flows.
- Standardize Redis connectivity: either everything through HAProxy (recommended), or consistently use the code‑level failover abstraction via DI.


## System Map (What’s Running Today)

- Task execution: Celery app (`swarm/celery_app.py`)
  - Broker/backend: Redis URLs via `CELERY_BROKER_URLS` or `REDIS__URL`.
  - Robust connection settings: pool limits, retry, visibility timeout, acks late, task events.
  - Queues defined: `browser`, `tankpit`, `llm`, `default`.
  - Router: `BrowserSessionRouter` routes browser tasks by `task_id` to per‑worker direct queues (`browser.direct.<worker_id>`), else falls back to default routing.

- Browser tasks: `swarm/tasks/browser.py`
  - Task‑scoped browser engines; session registry in Redis (TTL‑based); cleanup on shutdown.
  - All tasks accept `task_id` to enforce session consistency.

- Job producer for Discord: `plugins/commands/web.py` using `CeleryBrowserRuntime` (`distributed/celery_browser.py`).

- Container management & autoscaling
  - Image builds: Dockerfile (runtime‑worker, runtime‑swarm, runtime‑autoscaler).
  - Autoscaler: `scripts/celery_autoscaler.py` (via Flower API), orchestrator via `DockerApiBackend` (also `KubernetesBackend`, `FlyIOBackend`).
  - Worker containers: started with labeled metadata and queues (including `browser.direct.<hostname>`), pointed to HAProxy Redis.

- Redis failover
  - Network‑level via HAProxy (`Dockerfile.haproxy`, `scripts/generate_haproxy_config.py`, `docker-compose.yml`).
  - Code‑level abstraction exists (`infra/redis_factory.py`, `infra/redis_backends.py`) but is rarely used by callers.

- Heartbeats & worker registry
  - Active: `WorkerLifecycle` (thread loop) under Celery signals; stores `browser:worker:<id>` and `browser:worker_sessions:<id>` (TTL).
  - Legacy (not wired): `distributed/monitoring/heartbeat.py` references a non‑existent `Worker` and writes to `worker:heartbeat:*` and a stream.

- Logging/observability
  - Centralized JSON logging with contextual metadata and dedupe (`core/logger_setup.py`).
  - Prometheus exporters; compose profiles for Flower, Prometheus, Grafana, Loki, Alloy.


## Verified Claims (with references)

- Redis failover is in place through HAProxy
  - Compose service `haproxy-redis` generates config from `CELERY_BROKER_URLS` and listens on 6380, exposing stats at 8080.
  - Worker containers are configured with `REDIS_URL`/`CELERY_BROKER_URLS` pointing to `redis://default:…@haproxy-redis:6380/0` (see `DockerApiBackend._create_worker_container`).

- Multiple container backends exist and are used
  - Docker API backend actively used by the autoscaler; K8s and Fly.io backends are implemented and selectable via flags/env.

- Celery routes + router in place
  - `task_routes` define static queues; `BrowserSessionRouter` directs browser tasks with `task_id` to `browser.direct.<worker_id>`.

- DI + settings are used in the Discord app
  - `dependency_injector` wires cogs and provides a Redis client (`core/containers.py`), and settings are via `pydantic-settings`.


## Job Queue System (Deep Dive)

Goal: Task‑scoped browser sessions should be routed deterministically to the owning worker for the life of the session; autoscaler should see demand and scale accordingly.

Current design elements:
- Session affinity: Router expects `kwargs["task_id"]` to map to `browser.direct.<worker_id>` via `browser:affinity:<task_id>`.
- Worker queues: Each worker consumes `browser` and its own `browser.direct.<hostname>` queue (see worker entrypoint).
- Tasks: All browser tasks accept `task_id` and default to `self.request.id` if omitted.

Gaps discovered:
1) CeleryBrowserRuntime does not pass `task_id` for most methods
   - In `distributed/celery_browser.py`, `goto`, `click`, and `screenshot` publish tasks without `task_id` in kwargs and force `queue="browser"`.
   - Consequences:
     - Router cannot apply session affinity; tasks hit the generic `browser` queue.
     - A new engine may be created per call because tasks default `task_id` to the new Celery task id, breaking session continuity.
     - Direct queues (`browser.direct.*`) remain unused by these calls.

2) Autoscaler queue visibility excludes per‑worker queues
   - `scripts/celery_autoscaler.py` fetches queue depths from Flower and only inspects the name derived from `DistributedConfig.worker_types[...].job_queue.split(":")[0]` (e.g., `browser`).
   - Tasks routed to `browser.direct.*` queues won’t contribute to `browser` queue depth, so demand on direct queues is invisible to the autoscaler. If affinity routing is fixed, this becomes a correctness issue for scaling.

3) Route mismatch for `browser.scrape_data`
   - Celery configuration routes `browser.scrape_data` to the `default` queue, but `CeleryBrowserRuntime.scrape_data` forces `queue="browser"`. The send‑time queue wins, making the static route misleading.

Net effect:
- Session affinity is conceptually right but not exercised by the current runtime client. Scaling logic risks under‑scaling because direct queues are ignored.

Recommendations (job queue):
- Pass `task_id` for all browser RPC calls in `CeleryBrowserRuntime` and stop forcing `queue="browser"` on calls that should be affinity‑routed; the router will choose the correct queue.
- Choose a single routing for `browser.scrape_data` (either keep it on `browser` or truly move it to `default`) and align code/config.
- Update autoscaler to aggregate queue depths across `browser` and all `browser.direct.*` queues (Flower’s `/api/queues/length` exposes all active queues). Sum depths for all names that start with `browser` to inform scaling decisions.


## Redis/Upstash Usage and Risk

What burns commands today:
- WorkerLifecycle heartbeat loop (every 20s by default):
  - Pipeline does `HSET` + `EXPIRE` (worker key) + `EXPIRE` (sessions set) and `SCARD` (for session count). Roughly 4 commands/beat ⇒ ~17,280/day/worker at 20s.
- Browser health monitor (every 15s):
  - `HSET` on `browser:health` (~5,760/day).
- Celery task traffic (enqueue/ack/events), often dominant under load.
- KEYS usage in registries (e.g., `WorkerRegistry`):
  - `keys("browser:worker:*")`, `keys("browser:affinity:*")`. If used in periodic flows, these are expensive and count against Upstash limits.

Failover:
- Network‑level HAProxy failover is deployed and used by containers and compose‑managed services. This is the primary, effective mitigation for Upstash outages/limits.
- Code‑level failover abstraction exists but is not the common path for most clients.

Recommendations (Redis):
- Increase `WORKER_HEARTBEAT_INTERVAL` to 60–120s to cut heartbeat ops 3–6×, and keep only the WorkerLifecycle heartbeat path.
- Replace KEYS with SCAN or maintain indexed sets/zsets (e.g., maintain a `browser:workers` set) for any runtime paths.
- Ensure all services in Docker connect to HAProxy (not direct Upstash URLs). Prefer a single pattern for local dev, too, to keep behavior consistent.
- Optionally standardize async clients through `infra/redis_factory.create_redis_client()` or fully embrace “HAProxy‑only” and retire code‑level failover.


## Heartbeats and Worker Registry

Active path (recommended):
- `swarm/distributed/worker_lifecycle.py` creates `browser:worker:<id>` and `browser:worker_sessions:<id>` with TTL and updates them in a thread heartbeat.

Legacy path (should remain unused):
- `swarm/distributed/monitoring/heartbeat.py` references `..worker.Worker` (missing) and also writes a stream (`xadd`). It is not wired into the running code.

Recommendations:
- Keep only `WorkerLifecycle`; remove/confine legacy heartbeat code to tests or deprecate it clearly to avoid accidental use.
- Avoid `SCARD` every beat; maintain the session count on add/remove and update periodically (e.g., on change or every N beats).


## Dependency Injection & Config Consistency

- Discord app uses `dependency_injector` well (cogs, settings, Redis client provider). However, many non‑Discord contexts (Celery tasks, autoscaler, router) create clients outside DI.
- The DI provider currently constructs a raw async Redis client, bypassing the failover abstraction.

Recommendations:
- Pick a single approach:
  - Preferred: always point at HAProxy and drop code‑level failover for simplicity.
  - Alternative: standardize client creation through `infra/redis_factory.create_redis_client()` via DI and use it everywhere (router can stay sync if needed).
- Normalize `decode_responses` usage to avoid mixed bytes/str parsing.


## Container Management & Autoscaling

What’s working:
- Docker API backend creates labeled, health‑checked worker containers with correct env (HAProxy endpoints, queues), and a per‑worker direct queue consumer.
- Autoscaler queries Flower for queue depth and scales containers.

Gaps:
- Backend selection is duplicated: DI pins `DockerApiBackend()` while the autoscaler selects its backend independently.
- Autoscaler currently looks only at the base `browser` queue; it should also aggregate `browser.direct.*` depths.
- No small “manager” process centralizes health/cleanup; this logic is split across Celery signals, a monitor cog, and tests.

Recommendations:
- Centralize orchestrator selection (env/setting) used by both DI and autoscaler.
- Extend autoscaler’s queue accounting to include per‑worker direct queues, or move to a capacity signal (e.g., Prometheus metric from workers) for smarter scaling.
- Optionally add a tiny `distributed/services/manager` that:
  - Exposes a consolidated HTTP `/health` and `/metrics`.
  - Performs periodic cleanup (orphan sessions, stale workers) using SCAN/indexed sets.
  - Consolidates current scattered loops.


## Logging & Observability

- Centralized JSON logging with context vars (service, worker_id, job_id, hostname, container_id, deployment_env, region) and dedupe filter to reduce noise.
- Compose profiles include Flower, Prometheus, Grafana, Loki, Alloy.
- Good defaults and environment overrides (LOG_LEVEL, LOG_FORMAT pretty/json, file handler opt‑in).

Recommendations:
- Add lightweight counters per component for Redis commands (estimates acceptable) to alert before hitting Upstash limits.
- Emit autoscaler decisions and per‑queue depths as metrics.


## Security/Config Hygiene

- `.env` contains real‑looking tokens/keys; it is ignored by git (good). Ensure no secrets are committed elsewhere and consider moving to env‑var injection in CI/CD, with a redacted `.env.example` for local use.


## Prioritized Action Plan

1) Fix browser session routing (high impact)
   - Pass `task_id` in all `CeleryBrowserRuntime` calls (`goto`, `click`, `fill`, `wait_for`, `screenshot`) using the session id returned from `start()`.
   - Stop forcing `queue="browser"` on those calls; let `BrowserSessionRouter` select `browser.direct.<worker>`.
   - Align `browser.scrape_data` queue: either publish without an explicit queue (let router/static route decide) or adjust config to reflect the chosen queue.

2) Update autoscaler accounting (high impact)
   - Include all queue names that start with `browser` (both `browser` and `browser.direct.*`) when computing depth, or switch to a capacity metric emitted by workers.

3) Reduce Redis command budget (medium impact)
   - Raise `WORKER_HEARTBEAT_INTERVAL` to 60–120s; keep only WorkerLifecycle.
   - Remove KEYS from runtime paths; where needed, maintain sets/zsets or use SCAN.
   - Confirm all services point to HAProxy; for local dev, prefer the same path for parity.

4) Unify orchestrator/DI configuration (medium impact)
   - Make orchestration backend a single setting consumed by both DI and autoscaler.
   - Decide on client creation pattern: HAProxy‑only or DI‑provided failover.

5) Optional manager service (nice to have)
   - Introduce a minimal `distributed/services/manager` to consolidate health checks, cleanup, and fleet summary endpoints.


## Validation Checklist (post‑changes)

- Session continuity
  - Start a session; run a sequence of operations; verify all tasks carry the same `task_id` in kwargs; confirm router logs route to the same `browser.direct.<id>` queue.
- Scaling correctness
  - Back up the `browser.direct.*` queues; observe autoscaler summing depths across those queues and scaling up workers.
  - Drain queues; observe scale‑down to min workers after cooldown.
- Redis budget
  - With increased heartbeat interval, estimate ops/day/worker; verify reduction in Upstash usage. Confirm no KEYS calls in periodic runtime paths.
- HAProxy failover
  - Stop Upstash (primary) and watch HAProxy route to local Redis; ensure processes continue to function.


## Appendix: File/Path References

- Celery app: `swarm/celery_app.py`
- Browser runtime client: `swarm/distributed/celery_browser.py`
- Browser tasks: `swarm/tasks/browser.py`
- Session router: `swarm/distributed/browser_router.py`
- Session registry: `swarm/distributed/session_registry.py`
- Worker lifecycle (heartbeat/registry): `swarm/distributed/worker_lifecycle.py`
- Worker registry (admin/util): `swarm/distributed/worker_registry.py`
- Autoscaler: `scripts/celery_autoscaler.py`
- Docker API backend: `swarm/distributed/backends/docker_api.py`
- Redis HAProxy: `Dockerfile.haproxy`, `scripts/generate_haproxy_config.py`, `scripts/entrypoint.haproxy.sh`, `docker-compose.yml`
- Logging: `swarm/core/logger_setup.py`
- DI container: `swarm/core/containers.py`
- Settings: `swarm/core/settings.py`

