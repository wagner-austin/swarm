"""
Validate that local/test Redis configuration is safe and isolated.

Expected defaults (based on this repo's compose and docs):
- REDIS_URL -> redis://...@localhost:6379/15
- CELERY_BROKER_URLS -> redis://...@haproxy-redis:6380/0

Prints the values and exits non-zero if the checks fail.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlparse


def _print_line(label: str, value: str) -> None:
    print(f"{label}={value}")


def _get_env(name: str) -> str | None:
    return os.environ.get(name)


def _check_redis_url(url: str) -> bool:
    p = urlparse(url)
    if p.scheme != "redis":
        print(f"[ERROR] REDIS_URL must use redis:// scheme, got: {p.scheme}")
        return False
    # Accept either direct local test DB (6379/15) or HAProxy (6380/0)
    is_local_test = (
        p.hostname in {"localhost", "127.0.0.1"}
        and p.port == 6379
        and (p.path or "").strip("/") == "15"
    )
    is_haproxy = (
        p.hostname in {"haproxy-redis", "localhost"}
        and p.port == 6380
        and (p.path or "").strip("/") == "0"
    )
    if not (is_local_test or is_haproxy):
        print(
            f"[ERROR] REDIS_URL must be local test 6379/15 or haproxy 6380/0, got host={p.hostname} port={p.port} db={(p.path or '').strip('/')}"
        )
        return False
    if not p.password:
        print("[ERROR] REDIS_URL must include a password component")
        return False
    return True


def _check_broker_urls(urls: str, *, haproxy_urls_present: bool) -> bool:
    # CELERY_BROKER_URLS may be a single URL or a ';'-separated list
    ok_any = False
    for part in urls.split(";"):
        part = part.strip()
        if not part:
            continue
        p = urlparse(part)
        if p.scheme not in {"redis", "rediss"}:
            print(f"[ERROR] Broker entry must use redis(s):// scheme, got: {p.scheme}")
            return False
        if not p.password:
            print("[ERROR] Broker entry must include a password component")
            return False
        # Mark ok if at least one entry targets haproxy 6380/0 or localhost:6380/0
        if (
            p.scheme == "redis"
            and p.hostname in {"haproxy-redis", "localhost"}
            and p.port == 6380
            and (p.path or "").strip("/") == "0"
        ):
            ok_any = True
    if not ok_any:
        if haproxy_urls_present:
            # Accept configuration where haproxy backends are specified via HAPROXY_REDIS_URLS
            return True
        print("[ERROR] CELERY_BROKER_URLS must include a haproxy-redis:6380/0 entry for tests")
        return False
    return True


def _fallback_value_for(name: str) -> str | None:
    pwd = os.environ.get("REDIS_PASSWORD")
    if name == "REDIS_URL" and pwd:
        return f"redis://default:{pwd}@localhost:6379/15"
    if name == "CELERY_BROKER_URLS" and pwd:
        return f"redis://default:{pwd}@haproxy-redis:6380/0"
    return None


def _load_env_file() -> dict[str, str]:
    env: dict[str, str] = {}
    p = Path(".env")
    if not p.exists():
        return env
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip()
        env[k] = v
    return env


def main() -> int:
    # Prefer REDIS_URL; fall back to nested REDIS__URL; finally compute safe default
    redis_url = _get_env("REDIS_URL") or _get_env("REDIS__URL") or _fallback_value_for("REDIS_URL")
    broker_urls = _get_env("CELERY_BROKER_URLS") or _fallback_value_for("CELERY_BROKER_URLS")

    if not redis_url or not broker_urls:
        # Try reading from .env directly
        envf = _load_env_file()
        if not redis_url:
            redis_url = envf.get("REDIS_URL") or envf.get("REDIS__URL") or redis_url
        if not broker_urls:
            broker_urls = envf.get("CELERY_BROKER_URLS") or broker_urls
        if (not redis_url or not broker_urls) and "REDIS_PASSWORD" in envf:
            # Attempt constructing safe defaults using password from file
            pwd = envf["REDIS_PASSWORD"]
            redis_url = redis_url or f"redis://default:{pwd}@localhost:6379/15"
            broker_urls = broker_urls or f"redis://default:{pwd}@haproxy-redis:6380/0"

    if not redis_url or not broker_urls:
        print("[ERROR] Unable to resolve required Redis envs (REDIS_URL/CELERY_BROKER_URLS)")
        return 1

    _print_line("REDIS_URL", redis_url)
    _print_line("CELERY_BROKER_URLS", broker_urls)

    envf = _load_env_file()
    haproxy_urls_present = "HAPROXY_REDIS_URLS" in os.environ or "HAPROXY_REDIS_URLS" in envf
    ok = _check_redis_url(redis_url) and _check_broker_urls(
        broker_urls, haproxy_urls_present=haproxy_urls_present
    )
    if not ok:
        return 1

    print("[OK] Test Redis configuration is safe and isolated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
