#!/usr/bin/env python3

"""
Swarm Health Inspector – diagnose Redis health snapshot visibility and worker status.

What it does (read-only):
- Lists relevant containers (swarm, redis, haproxy-redis, worker*)
- Reads REDIS__URL from the swarm container
- Fetches the browser:health snapshot via redis-cli inside the redis container (DB 0)
- Lists a few heartbeat keys
- Reads the same snapshot using redis-cli pointed at haproxy-redis:6380 (DB 0)
- Shows recent log snippets from the swarm and worker containers around health/heartbeat

Usage:
  python tools/inspect_health.py

Requirements:
- Docker CLI available on the host where this script runs
- The compose stack containers running (redis, haproxy-redis, swarm, workers)
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple


@dataclass
class CmdResult:
    code: int
    out: str
    err: str


def run(cmd: Sequence[str]) -> CmdResult:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return CmdResult(p.returncode, p.stdout.strip(), p.stderr.strip())


def docker_ps_names() -> list[str]:
    r = run(["docker", "ps", "--format", "{{.Names}}"])
    if r.code != 0:
        raise RuntimeError(f"docker ps failed: {r.err or r.out}")
    return [line.strip() for line in r.out.splitlines() if line.strip()]


def has_container(name: str, names: Iterable[str]) -> bool:
    ns = list(names)
    return any(n == name for n in ns)


def exec_env(container: str, var: str) -> str | None:
    r = run(
        ["docker", "exec", container, "sh", "-lc", f"printenv {shlex.quote(var)} | sed -n '1p'"]
    )
    if r.code != 0:
        return None
    return r.out if r.out else None


def exec_redis_cli(container: str, args: list[str]) -> CmdResult:
    base = ["docker", "exec", container, "sh", "-lc"]
    inner = ["redis-cli", *args]
    return run(base + [" ".join(shlex.quote(a) for a in inner)])


def print_section(title: str) -> None:
    print("\n== " + title + " ==")


def main() -> None:
    names = docker_ps_names()
    print_section("Containers")
    for n in names:
        print("-", n)

    # Known names
    swarm = next((n for n in names if n == "swarm"), None)
    redis = next((n for n in names if n == "redis"), None)
    haproxy = next((n for n in names if n == "haproxy-redis"), None)
    workers = [n for n in names if n.startswith("swarm_browser") or n.startswith("swarm-worker")]

    if not redis:
        raise RuntimeError("redis container not found")
    if not haproxy:
        print("(info) haproxy-redis not found – will query redis directly")

    print_section("Bot Redis URL (from swarm container)")
    if swarm:
        url = exec_env(swarm, "REDIS__URL")
        print("REDIS__URL:", url or "<unset>")
    else:
        print("swarm container not found – cannot read REDIS__URL")

    # Determine password
    pw = None
    if swarm:
        pw = exec_env(swarm, "REDIS_PASSWORD")
    if not pw:
        # fallback to host env
        pw = os.environ.get("REDIS_PASSWORD")
    if not pw:
        print("(warn) REDIS_PASSWORD not found in swarm env or host env; redis-cli may fail")

    print_section("Snapshot via redis (DB 0)")
    args = ["-n", "0", "HGETALL", "browser:health"]
    if pw:
        args = ["-a", pw] + args
    r1 = exec_redis_cli(redis, args)
    print(r1.out or r1.err)

    print_section("Heartbeat keys (first 10)")
    args_keys = ["-n", "0", "KEYS", "worker:heartbeat:browser:*"]
    if pw:
        args_keys = ["-a", pw] + args_keys
    rkeys = exec_redis_cli(redis, args_keys)
    # pretty print limited lines
    lines = [ln for ln in (rkeys.out.splitlines() if rkeys.out else []) if ln]
    for ln in lines[:10]:
        print(ln)
    if not lines:
        print("<no heartbeat keys>")

    if haproxy:
        print_section("Snapshot via haproxy-redis:6380 (DB 0)")
        # Use -h and -p to reach haproxy endpoint from inside redis container
        args_h = ["-h", "haproxy-redis", "-p", "6380", "-n", "0", "HGETALL", "browser:health"]
        if pw:
            args_h = ["-a", pw] + args_h
        r2 = exec_redis_cli(redis, args_h)
        print(r2.out or r2.err)

    print_section("Recent swarm logs (health)")
    if swarm:
        logs = run(["docker", "logs", "--tail", "500", swarm])
        for ln in logs.out.splitlines():
            if (
                "browser health" in ln.lower()
                or "pool healthy" in ln.lower()
                or "pool degraded" in ln.lower()
            ):
                print(ln)
    else:
        print("swarm container not found – skipping")

    print_section("Recent worker logs (heartbeat/status)")
    if workers:
        for w in workers[:2]:
            print(f"-- {w} --")
            logs = run(["docker", "logs", "--tail", "200", w])
            for ln in logs.out.splitlines():
                if any(s in ln.lower() for s in ["heartbeat", "browser.", "health", "monitoring"]):
                    print(ln)
    else:
        print("no worker containers matching 'swarm_browser*' or 'swarm-worker*'")

    print_section("Done")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("[error]", type(exc).__name__, str(exc))
