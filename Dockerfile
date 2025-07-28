# syntax=docker/dockerfile:1.7@sha256:dbbd5e059e8a07ff7ea6233b213b36aa516b4c53c645f1817a4dd18b83cbea56

# ----------------------------------------------------------------------
# Builder stage
# ----------------------------------------------------------------------
# Pin to amd64 so the image runs on Fly.io's default hosts and Chromium can
# run without the --no-sandbox hack.
FROM python:3.12-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_INSTALLER_MAX_RETRIES=5 \
    POETRY_HTTP_TIMEOUT=120 \
    PIP_DEFAULT_TIMEOUT=120

# Copy retry helper early so every stage can use it
COPY scripts/retry.sh /usr/local/bin/retry
# Normalize line endings and make executable (belt-and-braces for Windows)
RUN sed -i 's/\r$//' /usr/local/bin/retry && chmod +x /usr/local/bin/retry

# Install Poetry with retry
RUN --mount=type=cache,target=/root/.cache/pip \
    retry 3 pip install --no-cache-dir poetry==2.1.3 \
    && mkdir -p /opt/venv        # will later host Playwright cache

WORKDIR /app

# Copy lock / project metadata first for better Docker layer caching
COPY pyproject.toml poetry.lock* ./

# Install deps with BuildKit cache mounts and retry
ENV POETRY_VIRTUALENVS_CREATE=false
RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=cache,target=/root/.cache/pypoetry \
    retry 3 poetry install --only main --no-root --no-ansi --no-interaction

# Copy the source code in a late layer so it changes often without invalidating
# the heavy dependency layers.
COPY . .

# Install Chromium inside the virtual-env path so its cache can be copied to the
# runtime image without dragging the whole Poetry installation with it.
RUN retry 3 python -m playwright install chromium --with-deps \
    && mv /root/.cache/ms-playwright /opt/venv/playwright-cache

# ----------------------------------------------------------------------
# Runtime stage – main swarm process (default)
# ----------------------------------------------------------------------
FROM python:3.12-slim AS runtime-swarm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Copy retry helper from builder
COPY --from=builder /usr/local/bin/retry /usr/local/bin/retry

# Minimum Debian packages Playwright needs at runtime
# Single layer with update + install to avoid hash-sum mismatch
RUN --mount=type=cache,target=/var/cache/apt \
    retry 3 bash -c 'apt-get update -qq && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        libnss3 libatk1.0-0 libatk-bridge2.0-0 libgtk-3-0 libx11-xcb1 libdrm2 \
        libgbm1 libxcomposite1 libxdamage1 libxext6 libxfixes3 libxrandr2 \
        libxrender1 libfontconfig1 libasound2 libxtst6 curl xvfb x11vnc xauth x11-utils && \
    apt-get clean && rm -rf /var/lib/apt/lists/*'

# Copy Python + wheels from the builder layer
COPY --from=builder /usr/local /usr/local
# Keep only the browser bits from the Playwright cache
COPY --from=builder /opt/venv/playwright-cache /root/.cache/ms-playwright
# Copy application source (but NOT entrypoint.sh)
COPY --from=builder /app /app
# Copy all entrypoint scripts
COPY scripts/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY scripts/entrypoint.worker.sh /usr/local/bin/entrypoint.worker.sh
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/entrypoint.worker.sh

# Single source of truth – Settings.metrics_port defaults to 9200
ARG METRICS_PORT=9200
EXPOSE 9000 $METRICS_PORT 5900
ENV METRICS_PORT=$METRICS_PORT

# Healthcheck: ensure metrics endpoint is up
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:9200/metrics || exit 1

# Default entrypoint: main Discord frontend
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

# ----------------------------------------------------------------------
# Runtime stage – distributed worker
# ----------------------------------------------------------------------
FROM runtime-swarm AS runtime-worker

# Expose a different port for worker metrics by default
ARG WORKER_PORT=9100
EXPOSE $WORKER_PORT
ENV WORKER_PORT=$WORKER_PORT

# Worker entrypoint script is already copied from runtime-swarm stage
# Document: to use worker image, override entrypoint or use this stage
ENTRYPOINT ["/usr/local/bin/entrypoint.worker.sh"]

# ----------------------------------------------------------------------
# Runtime stage – autoscaler (minimal, no GUI dependencies)
# ----------------------------------------------------------------------
FROM python:3.12-slim AS runtime-autoscaler

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Copy retry helper from builder
COPY --from=builder /usr/local/bin/retry /usr/local/bin/retry

# Copy only Python dependencies from builder (no Playwright/browser stuff)
COPY --from=builder /usr/local /usr/local

# Copy application source
COPY --from=builder /app /app

# Install docker-compose for production autoscaling with retry
RUN --mount=type=cache,target=/var/cache/apt \
    retry 3 bash -c 'apt-get update -qq && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ca-certificates curl && \
    apt-get clean && rm -rf /var/lib/apt/lists/*' && \
    retry 3 curl -L "https://github.com/docker/compose/releases/download/v2.31.0/docker-compose-$(uname -s)-$(uname -m)" \
        -o /usr/local/bin/docker-compose && \
    chmod +x /usr/local/bin/docker-compose && \
    docker-compose --version

# The autoscaler is a standalone service - no special entrypoint
# Run with: python -m scripts.celery_autoscaler
