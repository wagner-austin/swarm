"""
Guard: prevent direct Redis client instantiation patterns and enforce wrapper usage.

Rules (kept minimal to match current repo patterns):
- Disallow direct calls to Redis()/StrictRedis() constructors.
- If a file calls redis.from_url(...), it must also call wrap_redis_sync/async.

Usage: python scripts/guard_no_direct_redis_refs.py <paths...>
Returns non-zero on violations.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Iterable


def iter_py_files(path: Path) -> Iterable[Path]:
    if path.is_dir():
        yield from (p for p in path.rglob("*.py") if p.is_file())
    elif path.suffix == ".py" and path.is_file():
        yield path


class _RedisGuard(ast.NodeVisitor):
    def __init__(self) -> None:
        self.has_from_url: bool = False
        self.has_wrapper_call: bool = False
        self.ctor_violations: list[tuple[int, int, str]] = []

    def visit_Call(self, node: ast.Call) -> None:
        fn = node.func
        # Detect redis.from_url(...)
        if isinstance(fn, ast.Attribute) and fn.attr == "from_url":
            if isinstance(fn.value, ast.Name) and fn.value.id == "redis":
                self.has_from_url = True
        # Detect direct constructors Redis()/StrictRedis()
        if isinstance(fn, ast.Name) and fn.id in {"Redis", "StrictRedis"}:
            self.ctor_violations.append((node.lineno, node.col_offset, fn.id))
        if isinstance(fn, ast.Attribute) and fn.attr in {"Redis", "StrictRedis"}:
            self.ctor_violations.append((node.lineno, node.col_offset, fn.attr))
        # Detect wrapper usage
        if isinstance(fn, ast.Name) and fn.id in {"wrap_redis_sync", "wrap_redis_async"}:
            self.has_wrapper_call = True
        self.generic_visit(node)


def check_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    g = _RedisGuard()
    g.visit(tree)

    errors: list[str] = []
    for line, col, kind in g.ctor_violations:
        errors.append(
            f"{path}:{line}:{col}: redis guard: direct {kind}() construction is forbidden"
        )
    if g.has_from_url and not g.has_wrapper_call:
        errors.append(f"{path}:1:1: redis guard: redis.from_url() requires wrap_redis_(sync|async)")
    return errors


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: guard_no_direct_redis_refs.py <paths...>")
        return 2
    violations: list[str] = []
    for arg in argv[1:]:
        for file in iter_py_files(Path(arg)):
            violations.extend(check_file(file))
    if violations:
        for v in violations:
            print(v)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
