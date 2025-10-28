# AI Task Execution System

A distributed, AI-powered task execution platform that decomposes complex requests into subtasks and orchestrates specialized workers (browser automation, LLMs, etc.) to complete them.

## What This Is

An intelligent assistant that can handle requests like:
- "Research upcoming environmental bills and prepare talking points"
- "Analyze and improve the logging system in my codebase"
- "Monitor this website daily and summarize changes"

## Key Features

- Task decomposition into manageable subtasks
- Distributed workers that scale from 1 to 1000+
- Multiple frontends (Discord today; more can be added)
- Capability-based routing and session affinity
- Strict typing (mypy --strict) and safety guards

## Quick Start

### Prerequisites
- Python 3.11+
- Poetry
- Docker (for containerized deployment)

### Installation

```bash
git clone <repository-url>
cd swarm
poetry install --with dev
poetry run playwright install chromium
cp .env.example .env
```

### Configuration

Edit `.env` with your settings. For local development, everything connects to Redis through HAProxy (port 6380):

```ini
# App configuration (nested env for pydantic)
REDIS__URL=redis://default:${REDIS_PASSWORD}@localhost:6380/0
CELERY_BROKER_URLS=${REDIS__URL}

# Frontend configuration
DISCORD_TOKEN=your-token-here
```

### Running the System

Development (single machine):
```bash
docker compose up -d          # Start Redis, HAProxy, autoscaler, observability, and swarm
docker compose logs -f swarm  # View swarm logs
docker compose logs -f autoscaler
```

Production (Kubernetes):
```bash
kubectl apply -f k8s/
kubectl scale deployment/worker --replicas=50
```

## Architecture

Monitoring: Celery Exporter (9808), Grafana (3000), Prometheus (9090)
Autoscaling: Celery Autoscaler (driven by queue depth)

### Port Configuration

- 9200: Swarm metrics
- 9808: Celery Exporter metrics
- 9090: Prometheus
- 3000: Grafana
- 3100: Loki
- 6379: Redis (direct)
- 6380: HAProxy Redis (failover surface)

## Development

```bash
make test      # Run all tests (safety guard enables/validates safe Redis use)
make lint      # Ruff fix/format + mypy strict + repo guards
make check     # Full pipeline (lint + tests + docker status)

# Cleanup targets
make clean     # Project-scoped: compose down --volumes/--rmi all, then rebuild
make clean-all # DANGEROUS: system-wide Docker wipe (containers/images/volumes/networks) then rebuild
```

## Documentation

- docs/plan.md – Implementation roadmap
- docs/claude.md – Collaboration guidelines and architecture notes
- docs/scaling-architecture.md – Distributed system design

## Current Status & Roadmap

✅ Celery migration complete
- Celery broker and typed browser runtime
- Session affinity via Redis + router
- Autoscaler-driven worker creation

## Contributing

This project uses production-grade standards:
- Strict typing everywhere (mypy --strict)
- Integration tests prioritized over mocks
- Clear documentation for decisions

## License

[Your license here]

---

## Contracts

Authoritative contract for health, routing, typing, and testing (see `docs/contracts.md`).
- Health derives exclusively from Redis heartbeats using a freshness rule; no control-plane calls in decision loops.
- Session affinity is stored as a Redis hash with `worker_id`, `direct_queue`, and `timestamp`; consumers never derive queue names.
- Strict typing is enforced via Protocols and TypedDicts; casts are avoided by using typed boundary wrappers.

