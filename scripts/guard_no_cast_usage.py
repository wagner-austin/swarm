"""
Guard: disallow typing.cast usage within given paths.

Usage: python scripts/guard_no_cast_usage.py <paths...>
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


class _CastChecker(ast.NodeVisitor):
    def __init__(self) -> None:
        self.violations: list[tuple[int, int, str]] = []

    def visit_Call(self, node: ast.Call) -> None:
        fn = node.func
        if isinstance(fn, ast.Name) and fn.id == "cast":
            self.violations.append((node.lineno, node.col_offset, "cast"))
        if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
            if fn.value.id == "typing" and fn.attr == "cast":
                self.violations.append((node.lineno, node.col_offset, "typing.cast"))
        self.generic_visit(node)


def check_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    c = _CastChecker()
    c.visit(tree)
    return [
        f"{path}:{ln}:{col}: disallow cast() usage ({what})" for (ln, col, what) in c.violations
    ]


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: guard_no_cast_usage.py <paths...>")
        return 2
    errors: list[str] = []
    for arg in argv[1:]:
        for file in iter_py_files(Path(arg)):
            errors.extend(check_file(file))
    if errors:
        for e in errors:
            print(e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
