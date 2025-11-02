# CI/CD Pipeline Changes (Tests and Integration)

This document summarizes the CI/CD changes made to stabilize tests, remove
hidden environment coupling, and make integration runs reproducible across
local and CI environments. No type-safety policy notes are included here.

## Overview

- Keep unit-test coverage enabled by ensuring the coverage plugin is installed.
- Make integration tests deterministic without relying on a `.env` file or host
  mounts in CI.
- Validate Docker Compose using the production file plus a test override.
- Ensure container entrypoints don’t mask test commands when running tests.

## Summary of Changes

- Test coverage plugin
  - Added `pytest-cov` to dev dependencies so `--cov` flags work in CI.
  - File: `pyproject.toml: [tool.poetry.group.dev.dependencies]`

- GitHub Actions workflow (`.github/workflows/ci.yml`)
  - Validate Compose using both files:
    - `docker compose -f docker-compose.yml -f docker-compose.test.yml config --quiet`
  - Build test images against the same pair of files.
  - Start only the services needed for tests (`redis`, `haproxy-redis`).
  - Run integration tests in two phases:
    - Host-run pytest for markers requiring only Redis/HAProxy wiring:
      - `poetry run pytest tests/ -v -m "integration"`
    - Container-run Celery integration script to keep in-network hostnames consistent:
      - `docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm \
         --entrypoint "" \
         -e REDIS_PASSWORD=… \
         swarm python /app/scripts/test_celery_integration.py`
  - Validate deployment build step builds the `runtime-swarm` target:
    - `docker build --target runtime-swarm -t swarm:ci .`

- Test override for Compose (`docker-compose.test.yml`)
  - Remove CI dependence on a `.env` file and host mounts:
    - `swarm` and `autoscaler`: `env_file: []`, `volumes: []`.
  - Force Redis connections to go through HAProxy (which is locally backed) and
    ensure only local Redis URLs are used in CI to avoid external rate limits.
  - Keep environment parity while swapping backends to local-only for tests.

## Why

- Reproducibility: CI should not require a developer’s `.env` file or their host
  filesystem paths. The test override strips those assumptions while keeping the
  service graph identical.
- Reliability: Coverage flags in unit tests rely on `pytest-cov`. Installing it
  removes fragile command adjustments.
- Clarity: Running the Celery integration from a container guarantees consistent
  service discovery (e.g., `redis` hostname) without leaking entrypoint behavior
  into test execution.

## How to Run Locally

- Unit tests with coverage (no Docker required):
  - `poetry run pytest tests/ -v --cov=swarm --cov-report=term-missing -m "not integration"`

- Integration tests (local Docker):
  1) Start only Redis + HAProxy using the test override
     - `docker compose -f docker-compose.yml -f docker-compose.test.yml up -d redis haproxy-redis`
  2) Run pytest for integration-marked tests on the host
     - `poetry run pytest tests/ -v -m "integration"`
  3) (Optional) Run the Celery integration script inside the `swarm` container
     - `docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm \
        --entrypoint "" swarm python /app/scripts/test_celery_integration.py`
  4) Tear down
     - `docker compose -f docker-compose.yml -f docker-compose.test.yml down -v`

## Rollback / Toggle

- To disable the test override, omit `-f docker-compose.test.yml` in local runs.
- If CI should rely on `.env` again (not recommended), remove the `env_file: []`
  and `volumes: []` overrides for `swarm`/`autoscaler` in `docker-compose.test.yml` and
  inject a minimal `.env` before Compose commands.

## Impact

- CI no longer fails due to missing `.env` or host-specific mounts.
- Coverage flags work consistently (plugin present).
- Integration runs align with the production service layout while using local-only
  dependencies in CI to avoid external variability.

