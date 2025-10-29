#!/usr/bin/env python3
"""
Guard: prohibit ad-hoc inline healthchecks in first-party services.

Rules:
- For first-party services, healthcheck.test must use the shared entrypoint:
    ["CMD", "python", "-m", "swarm.health", <subcommand>]
- Third-party services are whitelisted and may use their native checks.

Usage:
    python scripts/guard_no_inline_healthchecks.py docker-compose.yml [more.yml ...]

Exit codes:
    0 = OK
    1 = Violations found
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable

import yaml

WHITELIST: frozenset[str] = frozenset(
    {
        # Third-party services exempt from shared Python health module
        "redis",
        "haproxy-redis",
        "prometheus",
        "grafana",
        "loki",
        "alloy",
        "celery-exporter",
    }
)


def _is_dict(obj: object) -> bool:
    return isinstance(obj, dict)


def _as_str_list(obj: object) -> list[str] | None:
    if isinstance(obj, list) and all(isinstance(x, str) for x in obj):
        return list(obj)
    return None


def _iter_compose_files(argv: Iterable[str]) -> list[Path]:
    paths: list[Path] = []
    for a in argv:
        p = Path(a)
        if p.exists() and p.is_file():
            paths.append(p)
    return paths


def _load_yaml(path: Path) -> dict[str, object]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _service_health_violation(name: str, hc: object) -> str | None:
    if name in WHITELIST:
        return None

    if not _is_dict(hc):
        # Non-dict healthcheck cannot be validated; flag it
        return f"{name}: healthcheck must be a mapping (found {type(hc).__name__})"

    test = hc.get("test") if isinstance(hc, dict) else None
    cmd = _as_str_list(test)
    if cmd is None:
        return (
            f"{name}: healthcheck.test must be a string list, e.g."
            " ['CMD','python','-m','swarm.health','<subcommand>']"
        )

    # Enforce shared entrypoint for first-party services
    required = ["CMD", "python", "-m", "swarm.health"]
    if len(cmd) < 4 or cmd[:4] != required:
        return f"{name}: healthcheck.test must start with {required}, got {cmd!r}"

    return None


def main(argv: list[str]) -> int:
    files = _iter_compose_files(argv)
    if not files:
        return 0

    violations: list[str] = []
    for f in files:
        doc = _load_yaml(f)
        services = doc.get("services") if isinstance(doc, dict) else None
        if not isinstance(services, dict):
            continue
        for name, svc in services.items():
            if not isinstance(name, str) or not isinstance(svc, dict):
                continue
            hc = svc.get("healthcheck")
            if hc is None:
                continue
            v = _service_health_violation(name, hc)
            if v:
                violations.append(f"{f.name}: {v}")

    if violations:
        print("[HEALTHCHECK GUARD] Violations detected:")
        for v in violations:
            print(" -", v)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
