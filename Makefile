# Makefile — Poetry-aware workflow for Swarm project
# Run `make help` to see available targets.

.PHONY: install shell lint format test clean run build help \
        savecode savecode-test deploy logs secrets personas

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Windows shell fix – detect and use appropriate shell
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
POETRY  := poetry             # centralised Poetry command (override with POETRY=…)
RUN     := $(POETRY) run      # prefix to execute inside Poetry venv
PYTHON  := $(RUN) python
PIP     := $(RUN) pip
RUFF    := $(RUN) ruff
MYPY    := $(RUN) mypy
PYTEST  := $(RUN) pytest -rsxv
SWARM_TEST_MODE  := $(RUN) pytest -rsxv

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

shell:              ## activate Poetry shell (interactive)
	$(POETRY) shell

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

check: lint test docker-status

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
compose-test:                ## start test stack (local Redis only, no Upstash)
	docker compose -f docker-compose.yml -f docker-compose.test.yml up -d redis haproxy-redis flower autoscaler swarm
	@echo "⏳ Waiting for services to be healthy..."
	@$(PYTHON) -c "import time; time.sleep(5)"
	docker compose ps

test: install compose-test   ## run pytest suite with test stack
	$(PYTEST)

# ---------------------------------------------------------------------------
# Fly.io helpers – run `make deploy` when you’re happy with local tests
# ---------------------------------------------------------------------------

# List of vars we always want on Fly
FLY_VARS = DISCORD_TOKEN GEMINI_API_KEY OPENAI_API_KEY OWNER_ID \
           PROXY_ENABLED PROXY_PORT METRICS_PORT \
           REDIS_ENABLED REDIS_URL SWARM_TEST_MODE

# Push any **non-empty** env var from .env → Fly secrets
secrets: install               ## upload .env values to Fly (idempotent)
	@echo "🔐  Syncing secrets with Fly …"
	@$(PYTHON) scripts/sync_secrets.py

# Upload personas.yaml as Fly secret (defaults to ~/.config/swarm/secrets/personas.yaml)
PERSONAS_FILE ?= $(HOME)/.config/swarm/secrets/personas.yaml

.PHONY: personas personas-win personas-posix
# upload personas.yaml as the SWARM_SECRET_PERSONAS secret (plain YAML text)

ifeq ($(OS),Windows_NT)
# -------------------- Windows PowerShell implementation --------------------
personas: personas-win

personas-win:
	powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File scripts/update_personas.ps1
else
# -------------------------- Standard POSIX shell ---------------------------
personas: personas-posix

personas-posix:
	@echo "🚀  Updating personas secret …"
	@test -s "$(PERSONAS_FILE)" || (echo "❌  Personas file missing or empty: $(PERSONAS_FILE)"; exit 1)
	@fly secrets unset SWARM_SECRET_PERSONAS || true
	@fly secrets set SWARM_SECRET_PERSONAS="$$$(cat "$(PERSONAS_FILE)")"
endif

# Build & deploy current code to Fly
deploy: secrets personas         ## build & deploy current code to Fly
	fly deploy --remote-only --no-cache --build-arg BUILDKIT_PROGRESS=plain

# Tail live Fly logs
logs:                        ## tail live Fly logs
	flyctl logs -a swarm

# ---------------------------------------------------------------------------
# Docker / Redis helpers
# ---------------------------------------------------------------------------
build-swarm:
	docker compose build --no-cache swarm

build: build-swarm  ## alias for build-swarm

docker-clean-build:  ## Clean Docker build cache and rebuild (fixes snapshot errors)
	@echo "🧹 Cleaning Docker build cache to fix snapshot errors..."
	docker builder prune -af
	@echo "🔨 Rebuilding all services without cache..."
	docker compose build --no-cache

compose-up: haproxy-config  ## start local dev services via docker compose (Redis + HAProxy)
	docker compose up -d

compose-recreate:      ## recreate swarm container (after config change)
	docker compose up -d --force-recreate swarm

compose-recreate-all:
	docker compose up -d --force-recreate

compose: compose-up

compose-down:          ## stop and remove docker compose services
	docker compose down

docker-status:         ## show status of docker compose services
	docker compose ps

# HAProxy Redis Failover
haproxy-up:            ## start services with HAProxy Redis proxy
	docker compose -f docker-compose.yml -f docker-compose.haproxy.yml up -d

haproxy-config:        ## generate HAProxy config from Redis URLs
	@poetry run python scripts/generate_haproxy_config.py

haproxy-test:          ## test HAProxy Redis failover
	@poetry run python scripts/test_haproxy_failover.py

haproxy-stats:         ## open HAProxy stats dashboard
	@echo "Opening HAProxy stats at http://localhost:8080/stats"
	@python -m webbrowser http://localhost:8080/stats || true

# ---------------------------------------------------------------------------
# Bot container manual reload workflow
# ---------------------------------------------------------------------------
swarm-build:             ## Build the swarm Docker image
	docker compose build swarm

swarm-restart:           ## Restart the swarm container (after build or code update)
	docker compose restart swarm

swarm-logs:              ## Tail logs from the swarm container
	docker compose logs -f swarm

# ---------------------------------------------------------------------------
# Celery testing
# ---------------------------------------------------------------------------
test-celery:             ## Run Celery integration tests
	docker compose exec swarm python /app/scripts/test_celery_integration.py

test-browser-job:        ## Test browser job submission through Celery
	docker compose exec swarm python /app/scripts/test_browser_job.py

celery-status:           ## Check Celery workers and queues
	@echo "=== Celery Workers ==="
	@docker compose exec swarm celery -A swarm.celery_app inspect active_queues || echo "No workers running"
	@echo "\n=== Flower Status ==="
	@curl -s http://localhost:5555/api/workers | python -m json.tool | head -20 || echo "Flower not accessible"
	@echo "\n=== Autoscaler Logs ==="
	@docker compose logs --tail=10 autoscaler

swarm-shell:             ## Open a shell in the running swarm container
	docker compose exec swarm bash

# ---------------------------------------------------------------------------
# Bot update: build, restart, and start if not running
# ---------------------------------------------------------------------------
swarm-update: ## Build, (re)start swarm container, and auto-tail logs
	@echo "🔄 Building swarm image..."
	@make swarm-build
	@docker compose up -d swarm
	@echo "📜 Tailing swarm logs (Ctrl+C to exit)..."
	@make swarm-logs

swarm-health: ## Check health status of the swarm container (requires HEALTHCHECK in Dockerfile)
	docker inspect --format='{{.State.Health.Status}}' swarm || echo "no health status (no HEALTHCHECK or not running)"

# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------
run: install                ## launch the Swarm (sync with pyproject script)
	@echo "Starting autoscaler in background..."
	@$(PYTHON) scripts/start_autoscaler.py
	@echo "Waiting for autoscaler to initialize..."
	@$(PYTHON) -c "import time; time.sleep(2)"
	$(PYTHON) -m swarm.core

build: install              ## build wheel / sdist
	$(POETRY) build

clean: install              ## remove Python / tool caches
	-@$(RUN) python -c "import pathlib, shutil; [(shutil.rmtree(p) if p.is_dir() else p.unlink()) if p.exists() else None for pattern in ['__pycache__', '.pytest_cache', '.ruff_cache', '.mypy_cache', '*.egg-info'] for p in pathlib.Path('.').rglob(pattern)]; print('Cleaned cache files')"

# Use savecode to save files
savecode:
	savecode . --skip tests --ext toml py yml

# Use savecode to save files
savecode-test:
	savecode . --ext toml py