#!/bin/sh
set -e

echo "[haproxy entrypoint] Starting HAProxy Redis failover service at $(date)"
echo "[haproxy entrypoint] Environment check:"
echo "  - CELERY_BROKER_URLS: ${CELERY_BROKER_URLS:-NOT SET}"
echo "  - HAPROXY_CONFIG_OUTPUT: ${HAPROXY_CONFIG_OUTPUT:-/config/haproxy-redis-generated.cfg}"

# Generate HAProxy configuration from environment variables
echo "[haproxy entrypoint] Generating HAProxy configuration..."
HAPROXY_CONFIG_OUTPUT=/config/haproxy-redis-generated.cfg python3 /scripts/generate_haproxy_config.py

if [ -f /config/haproxy-redis-generated.cfg ]; then
    echo "[haproxy entrypoint] Configuration generated successfully"
    echo "[haproxy entrypoint] HAProxy will listen on port 6380 for Redis connections"
else
    echo "[haproxy entrypoint] ERROR: Configuration file not generated!"
    exit 1
fi

# Start HAProxy directly with the generated config
# (avoids permission issues with /usr/local/etc/haproxy/)
echo "[haproxy entrypoint] Starting HAProxy..."
exec haproxy -f /config/haproxy-redis-generated.cfg