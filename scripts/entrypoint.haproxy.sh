#!/bin/sh
set -e

# Generate HAProxy configuration from environment variables
echo "Generating HAProxy configuration..."
HAPROXY_CONFIG_OUTPUT=/config/haproxy-redis-generated.cfg python3 /scripts/generate_haproxy_config.py

# Start HAProxy directly with the generated config
# (avoids permission issues with /usr/local/etc/haproxy/)
exec haproxy -f /config/haproxy-redis-generated.cfg