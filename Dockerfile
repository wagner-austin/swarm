# syntax=docker/dockerfile:1

# ----------------------------------------------------------------------
# Builder stage
# ----------------------------------------------------------------------
# Pin to amd64 so the image runs on Fly.io's default hosts and Chromium can
# run without the --no-sandbox hack.
FROM python:3.12-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Install Poetry to build the virtual-env layer
RUN pip install --no-cache-dir poetry==2.1.3 \
    && mkdir -p /opt/venv        # will later host Playwright cache

WORKDIR /app

# Copy lock / project metadata first for better Docker layer caching
COPY pyproject.toml poetry.lock* ./

# install the deps that are *already* locked – but only the “main” ones, straight into the system site-packages
ENV POETRY_VIRTUALENVS_CREATE=false
RUN poetry install --only main --no-root --no-ansi --no-interaction

# Copy the source code in a late layer so it changes often without invalidating
# the heavy dependency layers.
COPY . .

# Install Chromium inside the virtual-env path so its cache can be copied to the
# runtime image without dragging the whole Poetry installation with it.
RUN python -m playwright install chromium --with-deps \
    && mv /root/.cache/ms-playwright /opt/venv/playwright-cache

# ----------------------------------------------------------------------
# Runtime stage – main bot (default)
# ----------------------------------------------------------------------
FROM python:3.12-slim AS runtime-bot

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Minimum Debian packages Playwright needs at runtime
RUN apt-get update -qq && apt-get install -y --no-install-recommends \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libgtk-3-0 libx11-xcb1 libdrm2 \
    libgbm1 libxcomposite1 libxdamage1 libxext6 libxfixes3 libxrandr2 \
    libxrender1 libfontconfig1 libasound2 libxtst6 curl xvfb x11vnc xauth x11-utils \
    && rm -rf /var/lib/apt/lists/*

# Copy Python + wheels from the builder layer
COPY --from=builder /usr/local /usr/local
# Keep only the browser bits from the Playwright cache
COPY --from=builder /opt/venv/playwright-cache /root/.cache/ms-playwright
# Copy application source (but NOT entrypoint.sh)
COPY --from=builder /app /app
# Copy all entrypoint scripts
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
COPY entrypoint.manager.sh /usr/local/bin/entrypoint.manager.sh
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/entrypoint.manager.sh

# Single source of truth – Settings.metrics_port defaults to 9200
ARG METRICS_PORT=9200
EXPOSE 9000 $METRICS_PORT 5900
ENV METRICS_PORT=$METRICS_PORT

# Healthcheck: ensure metrics endpoint is up
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:9200/metrics || exit 1

# Default entrypoint: main Discord bot
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

# ----------------------------------------------------------------------
# Runtime stage – distributed worker
# ----------------------------------------------------------------------
FROM runtime-bot AS runtime-worker

# Expose a different port for worker metrics by default
ARG WORKER_PORT=9100
EXPOSE $WORKER_PORT
ENV WORKER_PORT=$WORKER_PORT

# Copy the worker entrypoint script
COPY entrypoint.worker.sh /usr/local/bin/entrypoint.worker.sh
RUN chmod +x /usr/local/bin/entrypoint.worker.sh

# Document: to use worker image, override entrypoint or use this stage
# ENTRYPOINT ["/usr/local/bin/entrypoint.worker.sh"]
