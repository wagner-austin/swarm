# syntax=docker/dockerfile:1.7
###############################################################################
# 0. BASE – tiny Python runtime (no browser libs)
###############################################################################
FROM python:3.12-slim-bookworm AS base
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 POETRY_VIRTUALENVS_CREATE=false
WORKDIR /app

# minimal tools everyone needs (curl for health-checks etc.)
RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends curl wget ca-certificates && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

###############################################################################
# 1. BROWSER-BASE – base + Chromium system libraries
###############################################################################
FROM base AS browser-base
RUN apt-get update -qq && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        libnss3 libatk1.0-0 libatk-bridge2.0-0 libgtk-3-0 \
        libx11-xcb1 libxext6 libxfixes3 libxrandr2 libxrender1 libxdamage1 \
        libxcomposite1 libdrm2 libgbm1 libasound2 libxtst6 libxss1 \
        libdbus-glib-1-2 && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

###############################################################################
# 2. BUILDER – install Poetry, deps, Playwright and download browsers
###############################################################################
FROM browser-base AS builder

ARG POETRY_VERSION=2.1.0
# bump when you need newer engines
ARG PLAYWRIGHT_VERSION=1.48.0

RUN pip install --no-cache-dir poetry==${POETRY_VERSION}

COPY pyproject.toml poetry.lock* ./
RUN poetry install --only main --no-root --no-ansi --no-interaction

# Playwright + Chromium binaries (once, in builder layer)
RUN pip install --no-cache-dir playwright==${PLAYWRIGHT_VERSION} && \
    python -m playwright install --with-deps chromium

# finally add source code (done *after* deps for cache efficiency)
COPY . .

###############################################################################
# 3. RUNTIME-SWARM – Discord bot (no browser libs copied)
###############################################################################
FROM base AS runtime-swarm

# copy just the Python environment and entrypoint
COPY --from=builder /usr/local/lib/python3.12/site-packages \
                    /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app /app

COPY scripts/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY scripts/entrypoint.worker.sh /usr/local/bin/entrypoint.worker.sh
RUN chmod +x /usr/local/bin/entrypoint.sh \
 && chmod +x /usr/local/bin/entrypoint.worker.sh \
 && useradd -u 1001 -ms /bin/bash pwuser \
 && mkdir -p /app/logs \
 && chown -R pwuser:pwuser /app/logs
USER pwuser

ARG METRICS_PORT=9200
ENV METRICS_PORT=${METRICS_PORT}
EXPOSE ${METRICS_PORT}
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD curl -fsSL http://localhost:${METRICS_PORT}/metrics || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

###############################################################################
# 4. RUNTIME-WORKER – headless browser worker
###############################################################################
FROM browser-base AS runtime-worker

# Python environment
COPY --from=builder /usr/local/lib/python3.12/site-packages \
                    /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app /app

# Browsers: copy from root's cache to shared location
RUN mkdir -p /opt/ms-playwright
COPY --from=builder /root/.cache/ms-playwright /opt/ms-playwright
# Make browsers accessible to all users
RUN chmod -R 755 /opt/ms-playwright

# Entrypoint and user
COPY scripts/entrypoint.worker.sh /usr/local/bin/entrypoint.worker.sh
RUN chmod +x /usr/local/bin/entrypoint.worker.sh \
 && useradd -u 1001 -ms /bin/bash pwuser \
 && mkdir -p /app/logs \
 && chown -R pwuser:pwuser /app/logs
USER pwuser

# Tell Playwright where to find browsers
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
ENV WORKER_METRICS_PORT=9100
EXPOSE ${WORKER_METRICS_PORT}
ENTRYPOINT ["/usr/local/bin/entrypoint.worker.sh"]

###############################################################################
# 5. RUNTIME-WORKER-VNC – optional debug image (Xvfb + VNC)
###############################################################################
FROM runtime-worker AS runtime-worker-vnc
USER root
# only extra packages for debug
RUN apt-get update -qq && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        xvfb x11vnc websockify novnc && \
    mkdir -p /tmp/.X11-unix && chmod 1777 /tmp/.X11-unix && \
    apt-get clean && rm -rf /var/lib/apt/lists/*
USER pwuser
# Enable VNC for debug worker
ENV ENABLE_VNC=1
# VNC ports
EXPOSE 5900 6080

###############################################################################
# 6. RUNTIME-AUTOSCALER – Celery autoscaler (no Playwright)
###############################################################################
FROM base AS runtime-autoscaler

# Copy all Python packages from builder (includes aiohttp and all deps)
COPY --from=builder /usr/local/lib/python3.12/site-packages \
                    /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app /app

# Remove browser-related packages to keep it lean
RUN pip uninstall -y playwright pyppeteer pyee greenlet playwright-stealth 2>/dev/null || true

WORKDIR /app
CMD ["python", "-m", "scripts.celery_autoscaler"]

###############################################################################
# 7. RELEASE – default image for Fly (worker superset)
###############################################################################
# Make the final image include Playwright + Chromium so both the swarm and
# worker processes can import and run browser code. Fly will build the final
# stage by default unless a target is specified.
FROM runtime-worker AS release
ENTRYPOINT []
