#!/usr/bin/env python3
"""
Generate HAProxy configuration for Redis/Upstash backends.

Contract (robust and explicit, prevents drift):
- Input: ``CELERY_BROKER_URLS`` – semicolon‑separated list of Redis URLs in
  the Celery format. The first URL is the primary, the rest are backups.
- Uniform mode (all SSL or all non‑SSL):
  - Enable backend‑level tcp‑check and, when a single password applies to all
    servers, use AUTH + PING for health validation.
- Mixed mode (some SSL, some non‑SSL):
  - Do not use backend‑level tcp‑check (it cannot be expressed safely for mixed).
  - Use per‑server checks:
    * SSL servers: "ssl verify none check-ssl" so HAProxy performs a TLS handshake.
    * Non‑SSL servers: plain "check" (TCP connect).
  - This yields accurate health per server without ambiguous global behavior.

Usage:
    python scripts/generate_haproxy_config.py

Environment variables:
    CELERY_BROKER_URLS: Semicolon-separated list of Redis URLs
        Example: "rediss://host:port;redis://backup:6379"
    MAXCONN: Maximum concurrent connections (default: 256)
    TIMEOUT_CLIENT: Client timeout (default: 50s)
    TIMEOUT_SERVER: Server timeout (default: 50s)
"""

from __future__ import annotations

import os
import sys
from typing import TypedDict
from urllib.parse import urlparse

# Note: No need for dotenv in Docker - environment variables are set by docker-compose


# Use print for logging since we're in a minimal container
def log(message: str) -> None:
    """Log a message to stdout for Docker/Alloy to capture."""
    print(f"[haproxy-config] {message}", flush=True)


class _ServerConfig(TypedDict):
    name: str
    host: str
    port: int
    is_ssl: bool
    is_backup: bool
    username: str
    password: str | None


def parse_redis_url(url: str) -> _ServerConfig:
    """Parse a Redis URL into a typed server config."""
    parsed = urlparse(url)
    is_ssl: bool = parsed.scheme in ("rediss", "redis+ssl")
    host: str = parsed.hostname or "localhost"
    port: int = int(parsed.port or (6380 if is_ssl else 6379))
    password: str | None = parsed.password
    username: str = parsed.username or "default"
    return {
        "name": "",
        "host": host,
        "port": port,
        "password": password,
        "username": username,
        "is_ssl": is_ssl,
        "is_backup": False,
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
    servers: list[_ServerConfig] = []
    for i, url in enumerate(url_list):
        try:
            server: _ServerConfig = parse_redis_url(url)
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
    timeout_client: str = os.getenv("TIMEOUT_CLIENT", "50s")
    timeout_server: str = os.getenv("TIMEOUT_SERVER", "50s")

    config = f"""global
    # No daemon mode - must run in foreground for Docker
    maxconn {maxconn}
    log stdout local0 info  # Log at info level to see health check state changes

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
    option allbackups
    option redispatch  # Try next server on connection failure
    option log-health-checks  # Log health check results
    retries 3
    timeout connect 5s
    timeout server 30s  # Upstash idle timeout
    timeout client 28s  # Slightly less than server to avoid race condition
    timeout tunnel 28s  # For long-lived connections (pub/sub if used)
    option tcpka  # Enable TCP keepalive (tune sysctls or use send-proxy-v2)
"""

    # Check for mixed SSL/non-SSL servers
    ssl_schemes = {bool(s["is_ssl"]) for s in servers}
    mixed_ssl: bool = len(ssl_schemes) > 1

    if mixed_ssl:
        log("Mixed SSL and non-SSL Redis servers detected")
        log("Using per-server checks: check-ssl (TLS handshake) for SSL, plain check for non-SSL")
        config += "    # Mixed SSL/non-SSL mode – per-server health checks\n"
        config += "    # SSL servers: TLS handshake via 'check-ssl'; non-SSL: TCP connect 'check'\n"
    else:
        # All servers have same SSL setting - can use full health checks
        all_ssl: bool = True in ssl_schemes  # True if all SSL, False if all non-SSL

        # Get password from first server (assuming all use same auth)
        first_server: _ServerConfig = servers[0]
        password_str: str | None = first_server["password"] if first_server["password"] else None

        # Add tcp-check for full validation
        config += "    # Uniform SSL configuration - full AUTH+PING health checks enabled\n"
        config += "    option tcp-check  # Enable command-based health checks\n"

        # Build health check sequence based on SSL and auth requirements
        if all_ssl:
            # SSL servers - use tcp-check connect ssl
            config += "    # Health check for SSL Redis servers with AUTH+PING\n"
            config += "    tcp-check connect ssl\n"
        else:
            # Non-SSL servers - use plain tcp-check connect
            config += "    # Health check for non-SSL Redis servers with AUTH+PING\n"
            config += "    tcp-check connect\n"

        # Add AUTH if password is configured
        if password_str:
            # Build Redis RESP protocol frame: *2\r\n$4\r\nAUTH\r\n$<len>\r\n<password>\r\n
            resp_cmd = f"*2\r\n$4\r\nAUTH\r\n${len(password_str)}\r\n{password_str}\r\n"
            auth_hex = resp_cmd.encode().hex()
            config += f"    tcp-check send-binary {auth_hex}\n"
            config += "    tcp-check expect string +OK\n"

        # Always send PING to verify Redis is responsive
        config += '    tcp-check send "PING\\r\\n"\n'
        config += "    tcp-check expect string +PONG\n"

    config += "\n"

    # Add all servers dynamically
    for server in servers:
        # Build server line with appropriate options
        check_inter: str = "5s" if server["is_backup"] else "3s"
        check_fall: int = 3 if server["is_backup"] else 2

        # Base server configuration
        server_line = f"    server {server['name']} {server['host']}:{server['port']}"

        # Add check parameters
        server_line += f" check inter {check_inter} fall {check_fall} rise 2"

        # Add SSL options for SSL servers
        if server["is_ssl"]:
            server_line += " ssl verify none"
            # In mixed mode, ensure handshake for health check
            if mixed_ssl:
                server_line += " check-ssl"

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
