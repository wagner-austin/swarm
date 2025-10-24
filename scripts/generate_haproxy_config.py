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

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


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
    ssl_schemes = {s.get("is_ssl") for s in servers}
    mixed_ssl = len(ssl_schemes) > 1

    if mixed_ssl:
        log("WARNING: Mixed SSL and non-SSL Redis servers detected")
        log("WARNING: Health checks disabled - using connection-only validation")
        log("WARNING: Password changes won't be detected until traffic fails")
        log("INFO: Upstash (SSL) as primary, Local Redis (non-SSL) as backup")

        # List the servers for clarity
        for server in servers:
            scheme_type = "SSL" if server.get("is_ssl") else "non-SSL"
            role = "primary" if not server.get("is_backup") else "backup"
            log(f"  - {server['name']}: {server['host']}:{server['port']} ({scheme_type}, {role})")

        # For mixed mode: no health checks, rely on passive connection monitoring
        # ssl-hello-chk doesn't work with mixed SSL/non-SSL backends
        config += "    # Mixed SSL/non-SSL mode - connection checks only, no health validation\n"
        config += "    # WARNING: No active health checks - using passive checks only\n"
        config += "    # NOTE: Clients must send AUTH themselves (transparent proxy mode)\n"
    else:
        # All servers have same SSL setting - can use full health checks
        all_ssl = True in ssl_schemes  # True if all SSL, False if all non-SSL

        # Get password from first server (assuming all use same auth)
        first_server = servers[0]
        password_str = (
            str(first_server.get("password", "")) if first_server.get("password") else None
        )

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
        check_inter = "5s" if server.get("is_backup") else "3s"
        check_fall = 3 if server.get("is_backup") else 2

        # Base server configuration
        server_line = f"    server {server['name']} {server['host']}:{server['port']}"

        # Add check parameters
        server_line += f" check inter {check_inter} fall {check_fall} rise 2"

        # Add SSL options for SSL servers
        if server.get("is_ssl"):
            # Always need ssl verify none for data connections
            server_line += " ssl verify none"

            # Only add check-ssl if NOT in mixed mode (where ssl-hello-chk handles it)
            # Also don't add it if using tcp-check connect ssl (avoids double handshake)
            if not mixed_ssl:
                # In uniform mode with tcp-check connect ssl, check-ssl is redundant
                # but HAProxy needs it to know to use SSL for the health check connection
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
