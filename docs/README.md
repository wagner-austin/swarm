# Documentation Index

Use this index to navigate project documentation.

- Architecture
  - `scaling-architecture.md` — Scaling flow, autoscaler, backends
  - `service-architecture.md` — Services overview and startup flow
  - `browser-session-affinity-design.md` — Session routing and affinity

- Deployment & Operations
  - `fly-deployment.md` — Fly.io deployment guide
  - `haproxy-deployment.md` — HAProxy Redis proxy deployment
  - `celery-monitoring-setup.md` — Monitoring stack (Prometheus, Grafana, Loki)
  - `windows-setup.md` — Windows developer setup guide

- Redis & Resilience
  - `redis-failover-architecture.md` — Failover architecture via HAProxy
  - `redis-failover-summary.md` — Implementation summary & checklist
  - `redis-optimization.md` — Reducing Redis command usage & costs

- Frontends & Plugins
  - `frontend-adapters.md` — Adapter pattern for frontends
  - `capability-queue-mapping.md` — Mapping capabilities to queues

- Logging & Observability
  - `distributed-logging.md` — Logging architecture and best practices

- Contracts & Policies
  - `contracts.md` — System contracts (health, routing, typing, guards)
  - `service-cleanup-tasks.md` — Cleanup plan and verification steps


- docs/architecture-audit.md - Architecture audit findings
- docs/security-audit-report.md - Security audit summary
- docs/celery-migration.md - Celery migration notes