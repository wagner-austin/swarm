#!/usr/bin/env bash
# Entrypoint for distributed worker container
set -euo pipefail

# Modern Playwright runs perfectly headless without Xvfb (since Chromium v115)
# Only enable X11/VNC for debugging when explicitly requested
if [[ "${ENABLE_VNC:-0}" == "1" ]]; then
  echo "[worker] Launching Xvfb + VNC for headful debugging..."
  
  # Start X virtual framebuffer; -dpms flag disables DPMS extension queries
  Xvfb :99 -screen 0 1280x720x24 -ac -nolisten tcp -dpms &
  XVFB_PID=$!
  trap 'kill -TERM "$XVFB_PID"; wait "$XVFB_PID"' TERM INT
  
  # Wait for X server
  for i in {1..30}; do
    if xdpyinfo -display :99 >/dev/null 2>&1; then
      echo "[worker] Xvfb ready after ${i} attempts"
      break
    fi
    sleep 1
  done
  
  # Start VNC server for remote viewing
  x11vnc -display :99 -forever -nopw -quiet -rfbport 5900 -shared &
  
  # Start noVNC web interface if available
  if command -v websockify >/dev/null 2>&1; then
    # Check if noVNC is installed, otherwise skip web interface
    if [ -d "/usr/share/novnc" ]; then
      websockify --web=/usr/share/novnc/ 6080 localhost:5900 &
      echo "[worker] noVNC available at http://localhost:6080"
    else
      # Just proxy without web interface
      websockify 6080 localhost:5900 &
      echo "[worker] WebSocket proxy running on port 6080 (no web UI - use VNC client on port 5900)"
    fi
  fi
  
  export DISPLAY=:99
  export PLAYWRIGHT_HEADLESS=0  # Tell Playwright to open real browser windows
else
  echo "[worker] Starting in true headless mode - no Xvfb needed"
  export PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
fi

# Launch the Celery worker
QUEUE="${CELERY_QUEUES:-browser}"

# Get hostname and sanitize it for queue naming (replace @ with _)
HOSTNAME=$(hostname)
SAFE_HOSTNAME=$(echo "$HOSTNAME" | tr '@' '_')

# Pick the pool type based on the queue
if [[ "$QUEUE" == "browser" ]]; then
  POOL_TYPE="threads"         # Use threads pool for async browser tasks
  CONCURRENCY="${CELERY_CONCURRENCY:-2}"   # Default to 2 threads - loop-local engines handle it
  # Add direct queue for session affinity
  QUEUES="${QUEUE},browser.direct.${SAFE_HOSTNAME}"
else
  POOL_TYPE="prefork"
  CONCURRENCY="${CELERY_CONCURRENCY:-1}"
  QUEUES="$QUEUE"
fi

echo "[worker] Starting worker ${HOSTNAME} with queues: ${QUEUES}"

# Decide whether to emit Celery events (high Redis cost). Opt-in via env.
EVENTS_FLAG=""
if [[ "${CELERY_SEND_EVENTS:-false}" == "true" || "${WORKER_EVENTS:-false}" == "true" ]]; then
  EVENTS_FLAG="--events"
fi

exec python -m swarm.celery_worker \
      --queues="$QUEUES" \
      --pool="$POOL_TYPE" \
      --concurrency="$CONCURRENCY" \
      --loglevel="${CELERY_LOGLEVEL:-info}" \
      --max-tasks-per-child="${CELERY_MAX_TASKS:-100}" \
      ${EVENTS_FLAG}
