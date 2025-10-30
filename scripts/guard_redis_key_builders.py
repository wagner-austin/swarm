"""
Guard: enforce Redis key builders and prevent hard-coded key prefixes outside approved modules.

Usage: python scripts/guard_redis_key_builders.py <paths...>
Returns non-zero on violations.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable

PATTERNS: tuple[str, ...] = (
    "browser:affinity:",
    "worker:heartbeat:browser:",
    "browser:worker:",
    "browser:worker_sessions:",
    "browser:session:",
    "browser:health",
)

APPROVED: tuple[str, ...] = (
    "swarm/infra/redis_protocols.py",
    "swarm/infra/redis_lua.py",
    "swarm/infra/redis_keys.py",
    "swarm/distributed/session_registry.py",
    "swarm/distributed/worker_registry.py",
    "swarm/distributed/browser_router.py",
    "swarm/distributed/worker_lifecycle.py",
    "swarm/plugins/monitor/browser_health.py",
    "swarm/plugins/commands/web.py",
    "scripts/celery_autoscaler.py",
)


def iter_files(path: Path) -> Iterable[Path]:
    if path.is_dir():
        for p in path.rglob("*.py"):
            # Exempt tests
            if "tests" in p.parts:
                continue
            yield p
    elif path.suffix == ".py" and path.is_file():
        yield path


def is_approved(path: Path) -> bool:
    s = str(path).replace("\\", "/")
    return any(s.endswith(a) for a in APPROVED)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: guard_redis_key_builders.py <paths...>")
        return 2

    violations: list[str] = []
    for arg in argv[1:]:
        for f in iter_files(Path(arg)):
            if is_approved(f):
                continue
            text = f.read_text(encoding="utf-8", errors="ignore")
            for pat in PATTERNS:
                if pat in text:
                    violations.append(
                        f"{f}:1:1: redis-keys guard: hard-coded key prefix '{pat}' detected; use builders from swarm.infra.redis_keys"
                    )

    if violations:
        for v in violations:
            print(v)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
