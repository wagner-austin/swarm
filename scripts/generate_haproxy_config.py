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

    MAXCONN: Maximum concurrent connections (default: 256)
    TIMEOUT_CLIENT: Client timeout (default: 50s)
    TIMEOUT_SERVER: Server timeout (default: 50s)
"""

import os
import sys
from urllib.parse import urlparse


# Use print for logging since we're in a minimal container
def log(message: str) -> None:
    """Log a message to stdout for Docker/Alloy to capture."""
    print(f"[haproxy-config] {message}", flush=True)


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
        log("ERROR: No Redis URLs provided after parsing")
        raise ValueError("No Redis URLs provided")

    log(f"Configuring HAProxy for {len(url_list)} Redis backends")

    # Parse each URL into components
    servers = []
    for i, url in enumerate(url_list):
        try:
            server = parse_redis_url(url)
            # Generate unique server name based on index
            server["name"] = f"redis_{i}"
            # First server is primary, others are backups
            server["is_backup"] = i > 0
            servers.append(server)

            # Log server configuration (hide password)
            log(
                f"  Server {server['name']}: {server['host']}:{server['port']} "
                f"(SSL: {server['is_ssl']}, Backup: {server['is_backup']}, "
                f"Auth: {'YES' if server['password'] else 'NO'})"
            )
        except Exception as e:
            log(f"ERROR: Failed to parse Redis URL #{i + 1}: {e}")
            raise

    # Get maxconn from environment with validation
    try:
        maxconn = int(os.getenv("MAXCONN", "256"))
    except ValueError:
        log("Invalid MAXCONN value; defaulting to 256")
        maxconn = 256

    # Get timeout values from environment
    timeout_client = os.getenv("TIMEOUT_CLIENT", "50s")
    timeout_server = os.getenv("TIMEOUT_SERVER", "50s")

    config = f"""global
    # No daemon mode - must run in foreground for Docker
    maxconn {maxconn}
    log stdout local0 warning

defaults
    mode tcp
    timeout connect 5000ms
    timeout client {timeout_client}
    timeout server {timeout_server}
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

# Redis frontend - clients connect here without auth
# Clients connect to this port WITHOUT passwords in their URLs
frontend redis_frontend
    bind *:6380
    mode tcp
    default_backend redis_backend

backend redis_backend
    mode tcp
    balance first
    option tcp-check
    option allbackups
    option redispatch  # Try next server on connection failure
    retries 3
    timeout connect 5s
    timeout server 50s
"""

    # Health checks use password from URL parsing
    first_server = servers[0]
    if first_server.get("password"):
        password_str = str(first_server["password"])
        # Build Redis RESP protocol frame: *2\r\n$4\r\nAUTH\r\n$<len>\r\n<password>\r\n
        resp_cmd = f"*2\r\n$4\r\nAUTH\r\n${len(password_str)}\r\n{password_str}\r\n"
        auth_hex = resp_cmd.encode().hex()

        config += f"""
    # Health check sequence with AUTH
    tcp-check connect
    tcp-check send-binary {auth_hex}
    tcp-check expect string +OK
    tcp-check send "PING\\r\\n"
    tcp-check expect string +PONG
"""
    else:
        config += """
    # Health check sequence without AUTH
    tcp-check connect
    tcp-check send "PING\\r\\n"
    tcp-check expect string +PONG
"""

    # Add all servers dynamically
    for server in servers:
        # Build server line with appropriate options
        check_inter = "2s" if server.get("is_backup") else "3s"
        check_fall = 2 if server.get("is_backup") else 3

        server_line = (
            f"    server {server['name']} {server['host']}:{server['port']}"
            f" check inter {check_inter} fall {check_fall} rise 2"
        )

        # Add SSL options for SSL servers
        if server.get("is_ssl"):
            server_line += " ssl verify none check-ssl"

        # Mark backup servers
        if server.get("is_backup"):
            server_line += " backup"

        config += server_line + "\n"

    return config


def main() -> None:
    """Generate HAProxy config from environment variables."""
    log("Starting HAProxy configuration generation")

    # Use CELERY_BROKER_URLS format (semicolon-separated URLs)
    redis_urls = os.getenv("CELERY_BROKER_URLS")

    if not redis_urls:
        log("ERROR: CELERY_BROKER_URLS environment variable not set")
        log("Expected format: redis://host1:port;redis://host2:port")
        sys.exit(1)

    # Log sanitized URLs (hide passwords)
    urls_list = redis_urls.split(";")
    log(f"Found {len(urls_list)} Redis URLs in CELERY_BROKER_URLS")
    for i, url in enumerate(urls_list):
        if "@" in url:
            sanitized = url.split("@")[1]
            log(f"  URL {i + 1}: ...@{sanitized}")
        else:
            log(f"  URL {i + 1}: {url}")

    try:
        config = generate_haproxy_config(redis_urls)
    except Exception as e:
        log(f"FATAL: Failed to generate HAProxy config: {e}")
        sys.exit(1)

    # Output to stdout (can be redirected to file)
    print(config)

    # Also save to file if requested
    output_file = os.getenv("HAPROXY_CONFIG_OUTPUT", "config/haproxy-redis-generated.cfg")
    if output_file:
        log(f"Saving configuration to: {output_file}")
        try:
            os.makedirs(os.path.dirname(output_file), exist_ok=True)
            with open(output_file, "w") as f:
                f.write(config)
            log("Configuration saved successfully")
        except Exception as e:
            log(f"ERROR: Failed to write config file: {e}")
            sys.exit(1)

    # Log completion
    log("HAProxy configuration generation completed successfully")


if __name__ == "__main__":
    main()
