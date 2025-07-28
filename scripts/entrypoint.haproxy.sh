#!/bin/sh
set -e

# Generate HAProxy configuration from environment variables
echo "Generating HAProxy configuration..."
HAPROXY_CONFIG_OUTPUT=/config/haproxy-redis-generated.cfg python3 /scripts/generate_haproxy_config.py

# Copy to HAProxy's expected location
cp /config/haproxy-redis-generated.cfg /usr/local/etc/haproxy/haproxy.cfg

# Start HAProxy
exec haproxy -f /usr/local/etc/haproxy/haproxy.cfg