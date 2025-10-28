# Makefile - Poetry-aware workflow for Swarm project
# Minimal commands: start, stop, check

.PHONY: help install lint format test check \
        start stop docker-status \
        docker-kill-orphans docker-prune-project docker-wipe-all rebuild \
        clean clean-cache

# ---------------------------------------------------------------------------
# Windows shell fix - detect and use appropriate shell
# ---------------------------------------------------------------------------
ifeq ($(OS),Windows_NT)
    # Try common Git Bash locations
    POSSIBLE_SHELLS := \
        "C:/Program Files/Git/bin/bash.exe" \
        "C:/Program Files/Git/usr/bin/bash.exe" \
        "C:/Program Files (x86)/Git/bin/bash.exe" \
        "C:/Git/bin/bash.exe"

    # Find the first existing shell
    SHELL := $(firstword $(foreach s,$(POSSIBLE_SHELLS),$(wildcard $(s))) sh)
    .SHELLFLAGS := -c
endif

# ---------------------------------------------------------------------------
# Tooling helpers
# ---------------------------------------------------------------------------
POETRY  := poetry             # centralised Poetry command (override with POETRY=.)
RUN     := $(POETRY) run      # prefix to execute inside Poetry venv
PYTHON  := $(RUN) python
PIP     := $(RUN) pip
RUFF    := $(RUN) ruff
MYPY    := $(RUN) mypy
PYTEST  := $(RUN) python -c "import scripts.guard_flushdb_runtime as _g, pytest, sys; _g.install(); sys.exit(pytest.main(['-rsxv']))"
SWARM_TEST_MODE  := $(RUN) pytest -rsxv

# ---------------------------------------------------------------------------
# Compose helpers
# ---------------------------------------------------------------------------
PROJECT_NAME ?= swarm
# Compose file for normal development (test file is for CI only)
COMPOSE_FILES := -f docker-compose.yml
# Test compose file (local Redis only, no Upstash failover)
TEST_COMPOSE_FILES := -f docker-compose.yml -f docker-compose.test.yml
# Profiles to include for full stack start/stop (adjust as needed)
START_PROFILE_FLAGS ?= --profile monitoring --profile observability

# ---------------------------------------------------------------------------
# Meta / docs
# ---------------------------------------------------------------------------
help:               ## show this help message
ifeq ($(OS),Windows_NT)
	@$(PYTHON) -c "import re; lines = open('$(MAKEFILE_LIST)', encoding='utf-8').readlines(); targets = [(m.group(1), m.group(2)) for line in lines for m in [re.match(r'^([a-zA-Z_-]+):.*?##\s*(.*)$$', line)] if m]; [print(f' {t[0]:12} {t[1]}') for t in targets]"
else
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) | \
	 awk 'BEGIN {FS = ":.*?##"}; {printf " \033[36m%-12s\033[0m %s\n", $$1, $$2}'
endif

# ---------------------------------------------------------------------------
# Environment / dependencies
# ---------------------------------------------------------------------------
install:            ## resolve & install all dependencies (incl. dev)
	$(POETRY) lock
	$(POETRY) install --with dev

# ---------------------------------------------------------------------------
# Code quality
# ---------------------------------------------------------------------------
lint: install               ## ruff fix + ruff format + mypy strict type-check + yamllint
	$(PIP) install --quiet --disable-pip-version-check types-requests types-PyYAML
	- $(RUN) yamllint .
	- $(RUFF) check --fix .
	$(RUFF) format .
	- $(RUFF) check . --select D401 --fix
	$(MYPY) --strict swarm
	$(PYTHON) scripts/guard_test_redis_safety.py
	$(PYTHON) scripts/ruff_no_direct_discord_response.py swarm/ tests/
	$(PYTHON) scripts/guard_no_direct_redis_refs.py swarm/
	$(PYTHON) scripts/guard_no_redis_protocol_duplication.py
	$(PYTHON) scripts/guard_no_any_usage.py scripts/celery_autoscaler.py swarm/distributed/backends/
	$(PYTHON) scripts/guard_no_cast_usage.py swarm/
	$(PYTHON) scripts/guard_no_pcalls.py swarm/

format: lint               ## auto-format code base (ruff + black)
	$(RUFF) format .

check: lint test docker-status  ## run all checks (lint, test, show docker status)

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
test: install  ## run pytest suite (uses local Redis via TEST_COMPOSE_FILES in CI)
	$(PYTEST)

# ---------------------------------------------------------------------------
# Docker / Redis stack
# ---------------------------------------------------------------------------
start: install ## start ALL services and containers (default + test + profiles)
	docker compose $(COMPOSE_FILES) $(START_PROFILE_FLAGS) up -d

stop: ## stop ALL services and containers (keep volumes)
	docker compose $(COMPOSE_FILES) $(START_PROFILE_FLAGS) down --remove-orphans
	@$(MAKE) -s docker-kill-orphans

stop-test: ## stop test environment (for CI)
	docker compose $(TEST_COMPOSE_FILES) down --remove-orphans

docker-status:         ## show status of docker compose services
	docker compose ps

# ---------------------------------------------------------------------------
# Orphan/Network cleanup helpers
# ---------------------------------------------------------------------------
ifeq ($(OS),Windows_NT)
docker-kill-orphans:   ## force remove containers on $(PROJECT_NAME)_default network (if any)
	@echo "Killing containers on network $(PROJECT_NAME)_default if any..."
	@echo "Removing autoscaled worker containers by label (swarm.project=$(PROJECT_NAME)) if any..."
	-@docker ps -aq --filter "label=swarm.project=$(PROJECT_NAME)" 2>nul | findstr /r "." >nul && (docker rm -f $$(docker ps -aq --filter "label=swarm.project=$(PROJECT_NAME)") >nul 2>&1 && echo Removed labeled worker containers) || echo No labeled worker containers found
	-@docker ps -aq --filter "network=$(PROJECT_NAME)_default" 2>nul | findstr /r "." >nul && (docker rm -f $$(docker ps -aq --filter "network=$(PROJECT_NAME)_default") >nul 2>&1 && echo Removed orphan containers on $(PROJECT_NAME)_default) || echo No orphan containers on $(PROJECT_NAME)_default
	-@docker network inspect $(PROJECT_NAME)_default >nul 2>&1 && docker network rm $(PROJECT_NAME)_default >nul 2>&1 || echo Network $(PROJECT_NAME)_default already removed
else
docker-kill-orphans:   ## force remove containers on $(PROJECT_NAME)_default network (if any)
	@echo "Killing containers on network $(PROJECT_NAME)_default if any..."
	@ids=$$(docker ps -aq --filter "label=swarm.project=$(PROJECT_NAME)"); \
	if [ -n "$$ids" ]; then docker rm -f $$ids >/dev/null 2>&1; else echo "No labeled worker containers found"; fi
	@ids=$$(docker ps -aq --filter "network=$(PROJECT_NAME)_default"); \
	if [ -n "$$ids" ]; then docker rm -f $$ids >/dev/null 2>&1; else echo "No orphan containers on $(PROJECT_NAME)_default"; fi
	@docker network inspect $(PROJECT_NAME)_default >/dev/null 2>&1 && docker network rm $(PROJECT_NAME)_default >/dev/null 2>&1 || true
endif

docker-prune-project:  ## prune unused images/volumes and networks (destructive)
	@echo "Pruning unused Docker data (images, containers, networks, volumes)..."
	docker system prune -a --volumes -f

# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------
clean-cache: install        ## remove Python / tool caches (__pycache__, .pytest_cache, etc.)
	-@$(RUN) python -c "import pathlib, shutil; [(shutil.rmtree(p) if p.is_dir() else p.unlink()) if p.exists() else None for pattern in ['__pycache__', '.pytest_cache', '.ruff_cache', '.mypy_cache', '*.egg-info'] for p in pathlib.Path('.').rglob(pattern)]; print('Cleaned cache files')"

rebuild: install     ## rebuild containers from scratch and start
	docker compose $(COMPOSE_FILES) $(START_PROFILE_FLAGS) build --no-cache
	docker compose $(COMPOSE_FILES) $(START_PROFILE_FLAGS) up -d

ifeq ($(OS),Windows_NT)
docker-wipe-all:            ## DANGEROUS: remove ALL containers, images, volumes, prune networks (Windows)
	@echo "Removing ALL containers..."
	-@docker ps -aq 2>nul | findstr /r "." >nul && (docker rm -f $$(docker ps -aq) >nul 2>&1 && echo Removed containers) || echo No containers
	@echo "Removing ALL images..."
	-@docker images -aq 2>nul | findstr /r "." >nul && (docker rmi -f $$(docker images -aq) >nul 2>&1 && echo Removed images) || echo No images
	@echo "Removing ALL volumes..."
	-@docker volume ls -q 2>nul | findstr /r "." >nul && (docker volume rm -f $$(docker volume ls -q) >nul 2>&1 && echo Removed volumes) || echo No volumes
	@echo "Pruning unused networks..."
	-@docker network prune -f >nul 2>&1 || echo Networks pruned
else
docker-wipe-all:            ## DANGEROUS: remove ALL containers, images, volumes, prune networks (Unix)
	@echo "Removing ALL containers..."
	-@ids=$$(docker ps -aq); if [ -n "$$ids" ]; then docker rm -f $$ids >/dev/null 2>&1 && echo Removed containers; else echo "No containers"; fi
	@echo "Removing ALL images..."
	-@ids=$$(docker images -aq); if [ -n "$$ids" ]; then docker rmi -f $$ids >/dev/null 2>&1 && echo Removed images; else echo "No images"; fi
	@echo "Removing ALL volumes..."
	-@ids=$$(docker volume ls -q); if [ -n "$$ids" ]; then docker volume rm -f $$ids >/dev/null 2>&1 && echo Removed volumes; else echo "No volumes"; fi
	@echo "Pruning unused networks..."
	-@docker network prune -f >/dev/null 2>&1 || true
endif

clean: ## Stop and remove THIS project's containers/images/volumes, then rebuild
	@echo "Stopping compose stacks..."
	- docker compose $(COMPOSE_FILES) $(START_PROFILE_FLAGS) down --remove-orphans --volumes --rmi all
	- docker compose $(TEST_COMPOSE_FILES) down --remove-orphans --volumes --rmi all
	@$(MAKE) -s docker-kill-orphans
	@echo "Rebuilding containers from scratch..."
	@$(MAKE) -s rebuild

.PHONY: clean-all
clean-all: ## DANGEROUS: system-wide wipe of ALL Docker data, then rebuild
	@echo "Wiping ALL Docker data on this machine (containers, images, volumes, networks)..."
	@$(MAKE) -s docker-wipe-all
	@echo "Rebuilding containers from scratch..."
	@$(MAKE) -s rebuild


