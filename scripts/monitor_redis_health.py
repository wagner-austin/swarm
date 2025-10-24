#!/usr/bin/env python3
"""
Manual diagnostic tool for Redis health and failover status.

NOTE: This is a standalone diagnostic tool. For production monitoring, use:
- Grafana dashboards: http://localhost:3000
- Prometheus metrics: http://localhost:9090
- HAProxy stats: http://localhost:8080/stats
- Flower (Celery): http://localhost:5555

This script provides quick command-line diagnostics for:
1. HAProxy backend health status
2. Redis authentication failures
3. Connection errors and failover events
4. Which backend (Upstash/Local) is actually serving traffic

Usage:
    python scripts/monitor_redis_health.py        # One-time check
    python scripts/monitor_redis_health.py --watch  # Continuous monitoring
"""

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from typing import Any, Optional

import redis
import requests
from dotenv import load_dotenv
from redis.exceptions import AuthenticationError, ConnectionError as RedisConnectionError

# Load environment variables from .env file
load_dotenv()


def check_haproxy_stats() -> dict[str, Any]:
    """Check HAProxy stats endpoint for backend health."""
    try:
        # Get CSV stats from HAProxy
        response = requests.get("http://localhost:8080/stats;csv", timeout=2)

        stats = {
            "haproxy_up": response.status_code == 200,
            "stats_url": "http://localhost:8080/stats",
        }

        if response.status_code == 200:
            # Parse CSV stats
            lines = response.text.strip().split("\n")
            if lines:
                headers = lines[0].split(",")

                # Find column indices
                try:
                    pxname_idx = headers.index("# pxname")
                    svname_idx = headers.index("svname")
                    status_idx = headers.index("status")
                    check_status_idx = headers.index("check_status")
                    stot_idx = headers.index("stot")  # total sessions
                    scur_idx = headers.index("scur")  # current sessions
                except ValueError:
                    # Headers not found, fall back to UNKNOWN
                    stats["upstash_status"] = "UNKNOWN"
                    stats["local_status"] = "UNKNOWN"
                    return stats

                # Parse each backend server
                for line in lines[1:]:
                    fields = line.split(",")
                    if len(fields) > status_idx and fields[pxname_idx] == "redis_backend":
                        server_name = fields[svname_idx]
                        status = fields[status_idx]
                        check_status = fields[check_status_idx]
                        total_sessions = fields[stot_idx]
                        current_sessions = fields[scur_idx]

                        if server_name == "redis_0":  # Upstash
                            if status == "UP":
                                if int(current_sessions) > 0 or int(total_sessions) > 0:
                                    stats["upstash_status"] = "UP (Primary - Active)"
                                else:
                                    stats["upstash_status"] = "UP (Primary)"
                            else:
                                stats["upstash_status"] = f"DOWN ({check_status})"

                        elif server_name == "redis_1":  # Local Redis
                            if status == "UP":
                                if int(current_sessions) > 0:
                                    stats["local_status"] = "UP (Active - Failover)"
                                    stats["failover_active"] = True
                                else:
                                    stats["local_status"] = "UP (Backup)"
                            else:
                                stats["local_status"] = f"DOWN ({check_status})"

                # Determine active backend
                if stats.get("failover_active"):
                    stats["active_backend"] = "Local Redis (Backup)"
                else:
                    upstash_status = stats.get("upstash_status", "")
                    if isinstance(upstash_status, str) and "UP" in upstash_status:
                        stats["active_backend"] = "Upstash (Primary)"
                    else:
                        stats["active_backend"] = "UNKNOWN"

        return stats

    except Exception as e:
        return {"haproxy_up": False, "error": str(e)}


def check_redis_auth() -> dict[str, Any]:
    """Check for Redis authentication failures."""
    auth_issues: dict[str, list[dict[str, Any]]] = {"auth_errors": [], "connection_errors": []}

    # Check application logs for auth failures
    containers = ["swarm", "swarm_browser_1", "haproxy-redis"]

    for container in containers:
        try:
            result = subprocess.run(
                ["docker", "logs", container, "--tail", "100", "--since", "5m"],
                capture_output=True,
                text=True,
                timeout=5,
            )

            logs = result.stderr + result.stdout

            # Look for auth failures
            auth_patterns = [
                r"ERR invalid password",
                r"NOAUTH Authentication required",
                r"AuthenticationError",
                r"Authentication failed",
                r"invalid password",
            ]

            for pattern in auth_patterns:
                matches = re.findall(pattern, logs, re.IGNORECASE)
                if matches:
                    auth_issues["auth_errors"].append(
                        {
                            "container": container,
                            "pattern": pattern,
                            "count": len(matches),
                            "sample": matches[0] if matches else None,
                        }
                    )

            # Look for connection errors
            conn_patterns = [
                r"Connection refused",
                r"Connection reset",
                r"Connection timeout",
                r"redis.exceptions.ConnectionError",
                r"Could not connect to Redis",
            ]

            for pattern in conn_patterns:
                matches = re.findall(pattern, logs, re.IGNORECASE)
                if matches:
                    auth_issues["connection_errors"].append(
                        {"container": container, "pattern": pattern, "count": len(matches)}
                    )

        except subprocess.TimeoutExpired:
            auth_issues["connection_errors"].append(
                {"container": container, "error": "Timeout checking logs"}
            )
        except Exception as e:
            auth_issues["connection_errors"].append({"container": container, "error": str(e)})

    return auth_issues


def test_redis_connections() -> dict[str, Any]:
    """Test actual Redis connections through HAProxy."""
    results: dict[str, Any] = {}

    # Test connection through HAProxy
    haproxy_url = "redis://default:{}@localhost:6380/0".format(os.getenv("REDIS_PASSWORD", ""))

    try:
        client: redis.Redis[Any] = redis.from_url(haproxy_url, socket_connect_timeout=2)
        if client.ping():
            results["haproxy_connection"] = "[OK]"

            # Try to determine which backend responded
            info = client.info("server")  # type: ignore[attr-defined]
            if "upstash" in str(info).lower():
                results["active_backend"] = "Upstash"
            else:
                results["active_backend"] = "Local Redis"

    except AuthenticationError:
        results["haproxy_connection"] = "[FAIL] Auth Failed"
    except RedisConnectionError as e:
        results["haproxy_connection"] = f"[FAIL] Connection Failed: {e}"
    except Exception as e:
        results["haproxy_connection"] = f"[ERROR] {e}"

    return results


def generate_report(watch_mode: bool = False) -> None:
    """Generate a comprehensive health report."""

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not watch_mode:
        print(f"\n{'=' * 60}")
        print(f"Redis Health Monitor Report - {timestamp}")
        print(f"{'=' * 60}\n")

    # 1. Check HAProxy Stats
    print("== HAProxy Status ==")
    haproxy_stats = check_haproxy_stats()

    if haproxy_stats.get("haproxy_up"):
        print("  [OK] HAProxy is running")
        print(f"  Stats URL: {haproxy_stats.get('stats_url', 'N/A')}")
        print(f"  - Upstash: {haproxy_stats.get('upstash_status', 'UNKNOWN')}")
        print(f"  - Local Redis: {haproxy_stats.get('local_status', 'UNKNOWN')}")
        print(f"  > Active Backend: {haproxy_stats.get('active_backend', 'UNKNOWN')}")

        if haproxy_stats.get("failover_active"):
            print("  [WARNING] FAILOVER ACTIVE - Running on backup!")
    else:
        print("  [FAIL] HAProxy is down or unreachable")
        if haproxy_stats.get("error"):
            print(f"     Error: {haproxy_stats['error']}")

    # 2. Test Redis Connections
    print("\n== Connection Test ==")
    conn_test = test_redis_connections()
    print(f"  HAProxy -> Redis: {conn_test.get('haproxy_connection', 'UNKNOWN')}")
    if conn_test.get("active_backend"):
        print(f"  Active Backend: {conn_test['active_backend']}")

    # 3. Check for Auth/Connection Issues
    print("\n== Authentication & Connection Issues ==")
    auth_issues = check_redis_auth()

    if auth_issues["auth_errors"]:
        print("  [WARNING] Authentication Errors Detected:")
        for error in auth_issues["auth_errors"]:
            print(
                f"    - {error['container']}: {error['count']} errors matching '{error['pattern']}'"
            )
    else:
        print("  [OK] No authentication errors in last 5 minutes")

    if auth_issues["connection_errors"]:
        print("  [WARNING] Connection Errors Detected:")
        for error in auth_issues["connection_errors"]:
            if "error" in error:
                print(f"    - {error['container']}: {error['error']}")
            else:
                print(f"    - {error['container']}: {error['count']} errors")
    else:
        print("  [OK] No connection errors in last 5 minutes")

    # 4. Recommendations
    print("\n== Recommendations ==")

    if haproxy_stats.get("failover_active"):
        print("  [URGENT] Upstash is down, running on backup Redis!")
        print("     - Check Upstash service status")
        print("     - Review recent password rotations")
        print("     - Check network connectivity to Upstash")

    if auth_issues["auth_errors"]:
        print("  [WARNING] Auth failures detected:")
        print("     - Verify REDIS_PASSWORD in .env matches all services")
        print("     - Check if Upstash password was recently rotated")
        print("     - Ensure HAProxy is using correct auth token")

    if not haproxy_stats.get("haproxy_up"):
        print("  [URGENT] HAProxy is not running:")
        print("     - Run: docker-compose up -d haproxy-redis")
        print("     - Check: docker logs haproxy-redis")

    if (
        not auth_issues["auth_errors"]
        and not auth_issues["connection_errors"]
        and haproxy_stats.get("haproxy_up")
    ):
        print("  [OK] All systems operational")

    print(f"\n{'=' * 60}\n")


def watch_mode() -> None:
    """Continuously monitor and report issues."""
    print("Starting continuous monitoring (Ctrl+C to stop)...")
    print("Checking every 30 seconds...\n")

    last_failover_state = False

    try:
        while True:
            stats = check_haproxy_stats()
            auth = check_redis_auth()

            # Only report if there are issues or state changes
            current_failover = stats.get("failover_active", False)

            if current_failover != last_failover_state:
                timestamp = datetime.now().strftime("%H:%M:%S")
                if current_failover:
                    print(f"[{timestamp}] [FAILOVER] ACTIVATED - Switched to backup Redis!")
                else:
                    print(f"[{timestamp}] [RESOLVED] FAILOVER RESOLVED - Back to primary (Upstash)")
                last_failover_state = current_failover

            if auth["auth_errors"]:
                timestamp = datetime.now().strftime("%H:%M:%S")
                print(
                    f"[{timestamp}] [WARNING] Auth errors detected: {len(auth['auth_errors'])} issues"
                )

            if auth["connection_errors"]:
                timestamp = datetime.now().strftime("%H:%M:%S")
                print(
                    f"[{timestamp}] [WARNING] Connection errors: {len(auth['connection_errors'])} issues"
                )

            time.sleep(30)

    except KeyboardInterrupt:
        print("\nMonitoring stopped.")


def main() -> None:
    """Run the Redis health monitor."""
    if len(sys.argv) > 1 and sys.argv[1] == "--watch":
        watch_mode()
    else:
        generate_report()


if __name__ == "__main__":
    main()
