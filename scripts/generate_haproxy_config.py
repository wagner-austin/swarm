#!/usr/bin/env python3
"""
Generate HAProxy configuration for Redis failover.

This script generates HAProxy configuration for multiple Redis backends
using the same format as Celery for consistency.

Usage:
    python scripts/generate_haproxy_config.py

Environment variables:
    CELERY_BROKER_URLS: Semicolon-separated list of Redis URLs
        Example: "redis://primary:6379;redis://backup1:6379;redis://backup2:6379"

    The first URL is treated as primary, all others as backups.
"""

import os
import sys
from urllib.parse import urlparse


def parse_redis_url(url: str) -> dict[str, str | int | bool | None]:
    """Parse a Redis URL into components."""
    parsed = urlparse(url)

    # Determine if SSL is needed
    is_ssl = parsed.scheme in ("rediss", "redis+ssl")

    # Extract components
    host = parsed.hostname or "localhost"
    port = parsed.port or (6380 if is_ssl else 6379)
    password = parsed.password
    username = parsed.username or "default"

    return {
        "host": host,
        "port": port,
        "password": password,
        "username": username,
        "is_ssl": is_ssl,
        "scheme": parsed.scheme,
    }


def generate_haproxy_config(redis_urls: str) -> str:
    """Generate HAProxy configuration for Redis failover.

    Args:
        redis_urls: Semicolon-separated list of Redis URLs (matching Celery format)
                   Example: "redis://primary:6379;redis://backup1:6379;redis://backup2:6379"
    """
    # Parse semicolon-separated URLs (same format as CELERY_BROKER_URLS)
    url_list = [url.strip() for url in redis_urls.split(";") if url.strip()]

    if not url_list:
        raise ValueError("No Redis URLs provided")

    # Parse each URL into components
    servers = []
    for i, url in enumerate(url_list):
        server = parse_redis_url(url)
        # Generate unique server name based on index
        server["name"] = f"redis_{i}"
        # First server is primary, others are backups
        server["is_backup"] = i > 0
        servers.append(server)

    config = """global
    # No daemon mode - must run in foreground for Docker
    maxconn 256
    log stdout local0 warning

defaults
    mode tcp
    timeout connect 5000ms
    timeout client 50000ms
    timeout server 50000ms
    option tcplog
    log global
    retries 3

# Stats dashboard
frontend http_stats
    bind *:8080
    mode http
    stats enable
    stats uri /stats
    stats refresh 5s

# Redis frontend - clients connect here
frontend redis_frontend
    bind *:6380
    default_backend redis_backend

backend redis_backend
    mode tcp
    balance first
    option tcp-check
    option allbackups
"""

    # Determine health check type based on first server's auth settings
    # (assuming all servers use same auth for simplicity)
    first_server = servers[0]
    if first_server.get("password") and not first_server.get("is_ssl"):
        # For non-SSL with auth, we can do full health check
        config += f"""
    # Health check with authentication
    tcp-check connect
    tcp-check send AUTH\\ {first_server["password"]}\\r\\n
    tcp-check expect string +OK
    tcp-check send PING\\r\\n
    tcp-check expect string +PONG
    tcp-check send QUIT\\r\\n
    tcp-check expect string +OK
"""
    else:
        # For SSL or no auth, simple health check
        config += """
    # Enable tcp-check for scriptable health checks
    option tcp-check
    tcp-check connect
"""

    # Add all servers dynamically with per-server SSL settings
    for server in servers:
        # Build server line with appropriate options
        server_line = f"server {server['name']} {server['host']}:{server['port']}"

        # Add health check parameters
        check_inter = "2s" if server.get("is_backup") else "3s"
        check_fall = 2 if server.get("is_backup") else 3
        server_line += f" check inter {check_inter} fall {check_fall} rise 2"

        # Add SSL options for SSL servers
        if server.get("is_ssl"):
            server_line += " ssl verify none"
            # Add check-ssl for SSL health checks
            server_line += " check-ssl"

        # Mark backup servers
        if server.get("is_backup"):
            server_line += " backup"

        config += f"\n    {server_line}\n"

    return config


def main() -> None:
    """Generate HAProxy config from environment variables."""
    # Use CELERY_BROKER_URLS format (semicolon-separated URLs)
    redis_urls = os.getenv("CELERY_BROKER_URLS")

    if not redis_urls:
        print("Error: CELERY_BROKER_URLS environment variable not set", file=sys.stderr)
        print("Expected format: redis://host1:port;redis://host2:port", file=sys.stderr)
        sys.exit(1)

    config = generate_haproxy_config(redis_urls)

    # Output to stdout (can be redirected to file)
    print(config)

    # Also save to file if requested
    output_file = os.getenv("HAPROXY_CONFIG_OUTPUT", "config/haproxy-redis-generated.cfg")
    if output_file:
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with open(output_file, "w") as f:
            f.write(config)
        print(f"\nConfiguration saved to: {output_file}", file=sys.stderr)

        # Show parsed URLs for verification
        url_list = [url.strip() for url in redis_urls.split(";") if url.strip()]
        print(f"\nConfigured {len(url_list)} Redis backends:", file=sys.stderr)
        for i, url in enumerate(url_list):
            server = parse_redis_url(url)
            server_type = "primary" if i == 0 else f"backup-{i}"
            print(
                f"  {server_type}: {server['host']}:{server['port']} (SSL: {server['is_ssl']})",
                file=sys.stderr,
            )


if __name__ == "__main__":
    main()
