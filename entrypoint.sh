#!/usr/bin/env bash
# Persistent Xvfb + bot launcher
set -euo pipefail

# Set up X11 authentication
echo "[entrypoint] Setting up X11 authentication..."
touch ~/.Xauthority
xauth add :99 . $(openssl rand -hex 16)

# Launch Xvfb on :99 (start a new server only if one is not already running)
if ! xdpyinfo -display :99 >/dev/null 2>&1; then
  echo "[entrypoint] Starting Xvfb on :99 …"
  # Clean up any stale lock file that might prevent Xvfb from starting again
  rm -f /tmp/.X99-lock || true
  # Launch Xvfb in the background (no -noreset so it exits when last client disconnects)
  # -ac allows all connections for simplicity in container
  Xvfb :99 -screen 0 1280x720x24 -ac -nolisten tcp &
  XVFB_PID=$!
  # Forward TERM/INT to Xvfb so Docker can shut it down cleanly
  trap 'echo "[entrypoint] Caught stop signal, terminating Xvfb…"; kill -TERM "$XVFB_PID"; wait "$XVFB_PID"' TERM INT
  
  # Wait for Xvfb to be fully ready
  echo "[entrypoint] Waiting for Xvfb to be ready..."
  for i in {1..30}; do
    if xdpyinfo -display :99 >/dev/null 2>&1; then
      echo "[entrypoint] Xvfb is ready after ${i} attempts"
      break
    fi
    sleep 1
  done
  
  if ! xdpyinfo -display :99 >/dev/null 2>&1; then
    echo "[entrypoint] ERROR: Xvfb failed to start properly"
    exit 1
  fi
else
  echo "[entrypoint] Reusing existing X server on :99"
fi

export DISPLAY=:99

# Start VNC server for remote viewing (optional, runs in background)
echo "[entrypoint] Starting VNC server on :0 (port 5900)..."
x11vnc -display :99 -forever -nopw -quiet -rfbport 5900 -shared &

# Verify X11 is working
echo "[entrypoint] Testing X11 connection..."
if ! xdpyinfo -display :99 >/dev/null 2>&1; then
  echo "[entrypoint] ERROR: Cannot connect to X server"
  exit 1
fi

echo "[entrypoint] X11 setup complete, starting bot..."

# Execute the bot
exec python -m bot.core
