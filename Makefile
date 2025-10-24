# Makefile - Poetry-aware workflow for Swarm project
# Minimal commands: start, stop, check

.PHONY: help install lint format test check \
        start stop docker-status haproxy-config \
        docker-kill-orphans docker-prune-project \
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
PYTEST  := $(RUN) pytest -rsxv
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
	$(MYPY) --strict .
	$(PYTHON) scripts/ruff_no_direct_discord_response.py swarm/ tests/

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
haproxy-config: install        ## generate HAProxy config from Redis URLs
	@poetry run python scripts/generate_haproxy_config.py

start: haproxy-config ## start ALL services and containers (default + test + profiles)
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
	@powershell -NoProfile -Command "\
		$$labelIds = docker ps -aq --filter 'label=swarm.project=$(PROJECT_NAME)'; \
		if ($$labelIds) { docker rm -f $$labelIds | Out-Null; Write-Output 'Removed labeled worker containers'; } \
		else { Write-Output 'No labeled worker containers found'; }"
	@powershell -NoProfile -Command "\
		$$ids = docker ps -aq --filter 'network=$(PROJECT_NAME)_default'; \
		if ($$ids) { docker rm -f $$ids | Out-Null; Write-Output 'Removed orphan containers on $(PROJECT_NAME)_default'; } \
		else { Write-Output 'No orphan containers on $(PROJECT_NAME)_default'; }"
	@powershell -NoProfile -Command "\
		$$ErrorActionPreference='SilentlyContinue'; \
		docker network inspect $(PROJECT_NAME)_default > $$null 2> $$null; \
		if ($$LASTEXITCODE -eq 0) { docker network rm $(PROJECT_NAME)_default > $$null 2> $$null }"
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

clean: clean-cache          ## alias for clean-cache
