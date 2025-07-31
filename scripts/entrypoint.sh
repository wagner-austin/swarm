#!/usr/bin/env bash
# Main swarm Discord bot entrypoint (no browser/X11 needed)
set -euo pipefail

echo "[entrypoint] Starting swarm Discord bot..."

# Execute the swarm
exec python -m swarm.core
