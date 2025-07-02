#!/usr/bin/env bash
# Entrypoint for distributed worker container
set -euo pipefail

# Optionally set up X11 if browser jobs are required
if [[ "${ENABLE_X11:-1}" == "1" ]]; then
  echo "[worker entrypoint] Setting up X11 for browser jobs..."
  touch ~/.Xauthority
  xauth add :99 . $(openssl rand -hex 16)
  if ! xdpyinfo -display :99 >/dev/null 2>&1; then
    rm -f /tmp/.X99-lock || true
    Xvfb :99 -screen 0 1280x720x24 -ac -nolisten tcp &
    XVFB_PID=$!
    trap 'kill -TERM "$XVFB_PID"; wait "$XVFB_PID"' TERM INT
    for i in {1..30}; do
      if xdpyinfo -display :99 >/dev/null 2>&1; then break; fi
      sleep 1
    done
    if ! xdpyinfo -display :99 >/dev/null 2>&1; then
      echo "[worker entrypoint] ERROR: Xvfb failed to start"
      exit 1
    fi
  fi
  export DISPLAY=:99
fi

# Launch the worker entrypoint
exec python -m bot.distributed.worker "$@"
