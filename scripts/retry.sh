#!/usr/bin/env bash
#
#  retry <max_attempts> <cmd…>
#
#  • Exponential back-off (with jitter) between attempts
#  • Non-zero exit if all attempts fail
#  • Echoes progress so CI logs show what's happening
set -euo pipefail

max=${1:-3}; shift
delay=5

for ((i=1; i<=max; i++)); do
  echo "▶️  attempt $i/$max: $*"
  if "$@"; then exit 0; fi
  if (( i == max )); then
    echo "❌ all $max attempts failed" >&2
    exit 1
  fi
  # jitter = 0-2 s
  jitter=$(( RANDOM % 3 ))
  echo "⏳ retrying in $((delay+jitter)) s…"
  sleep $((delay+jitter))
  delay=$((delay*2))
done