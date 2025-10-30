from __future__ import annotations

import argparse
import os
import socket
import sys
import urllib.request
from typing import Final

import redis

from swarm.infra.redis_keys import heartbeat_key
from swarm.infra.redis_protocols import RedisSyncProtocol, wrap_redis_sync


def _env(name: str) -> str | None:
    v = os.environ.get(name)
    return v if isinstance(v, str) and v != "" else None


def _resolve_redis_url() -> str:
    url = _env("REDIS_URL") or _env("REDIS__URL")
    if not url:
        raise SystemExit("REDIS_URL/REDIS__URL not set")
    return url


def _connect_redis(url: str) -> RedisSyncProtocol:
    client = redis.from_url(url, decode_responses=True, socket_connect_timeout=1)
    return wrap_redis_sync(client)


def _resolve_worker_id(explicit: str | None) -> str:
    if explicit:
        return explicit
    # Canonical worker id is host-only container hostname
    return socket.gethostname().strip() or "host"


def cmd_worker_heartbeat(args: argparse.Namespace) -> int:
    url = args.redis_url or _resolve_redis_url()
    worker_id = _resolve_worker_id(args.worker_id)
    client = _connect_redis(url)
    key = heartbeat_key(worker_id)
    ttl = client.ttl(key)
    return 0 if int(ttl) > 0 else 1


def _default_metrics_url() -> str | None:
    # Allow explicit URL via env if desired
    env_url = _env("HEALTH_HTTP_URL") or _env("SWARM_HEALTH_URL")
    if env_url:
        return env_url
    port = _env("METRICS_PORT")
    if port and port.isdigit():
        return f"http://localhost:{port}/metrics"
    return None


def cmd_http(args: argparse.Namespace) -> int:
    url = args.url or _default_metrics_url()
    if not url:
        # Require a resolvable URL either by flag or env
        return 1
    timeout: Final[float] = float(args.timeout)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            code = int(resp.getcode())
            return 0 if code == 200 else 1
    except Exception:
        return 1


def cmd_redis_ping(args: argparse.Namespace) -> int:
    url = args.redis_url or _resolve_redis_url()
    client = _connect_redis(url)
    try:
        ok = client.setex("__health_ping__", 1, "1")
        return 0 if bool(ok) else 1
    except Exception:
        return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="swarm.health", description="Swarm health checks")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_worker = sub.add_parser("worker-heartbeat", help="Check worker heartbeat in Redis")
    p_worker.add_argument("--redis-url", dest="redis_url", type=str, default=None)
    p_worker.add_argument("--worker-id", dest="worker_id", type=str, default=None)
    p_worker.set_defaults(func=cmd_worker_heartbeat)

    p_http = sub.add_parser("http", help="Check HTTP endpoint (defaults to METRICS_PORT/metrics)")
    p_http.add_argument("--url", dest="url", type=str, default=None)
    p_http.add_argument("--timeout", dest="timeout", type=int, default=5)
    p_http.set_defaults(func=cmd_http)

    p_redis = sub.add_parser("redis-ping", help="Verify Redis connectivity")
    p_redis.add_argument("--redis-url", dest="redis_url", type=str, default=None)
    p_redis.set_defaults(func=cmd_redis_ping)

    return p


def main() -> None:
    parser = build_parser()
    ns = parser.parse_args()
    code = ns.func(ns)
    raise SystemExit(int(code))


if __name__ == "__main__":
    main()
