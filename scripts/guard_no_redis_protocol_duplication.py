"""
Guard: ensure Redis Protocols are defined in a single canonical module.

Checks that RedisAsyncProtocol / RedisSyncProtocol are only declared
in swarm/infra/redis_protocols.py.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Iterable

ALLOWED_FILE = Path("swarm/infra/redis_protocols.py").as_posix()
TARGETS = {"RedisAsyncProtocol", "RedisSyncProtocol"}


def iter_py_files(root: Path) -> Iterable[Path]:
    yield from (p for p in root.rglob("*.py") if p.is_file())


def check_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name in TARGETS:
            # Confirm it looks like a Protocol subclass
            is_protocol = any(
                isinstance(b, ast.Name)
                and b.id == "Protocol"
                or isinstance(b, ast.Attribute)
                and b.attr == "Protocol"
                for b in node.bases
            )
            if is_protocol:
                rel = path.as_posix()
                if rel != ALLOWED_FILE:
                    violations.append(
                        f"{rel}:{node.lineno}:{node.col_offset}: duplicate {node.name} Protocol; use {ALLOWED_FILE}"
                    )
    return violations


def main() -> int:
    root = Path("swarm")
    if not root.exists():
        print("[ERROR] 'swarm' directory not found")
        return 2
    errors: list[str] = []
    for file in iter_py_files(root):
        errors.extend(check_file(file))
    if errors:
        for e in errors:
            print(e)
        return 1
    print("No duplicate Redis Protocol definitions found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
