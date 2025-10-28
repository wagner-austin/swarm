"""
Guard: disallow typing.Any usage in given paths.

Usage: python scripts/guard_no_any_usage.py <paths...>
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


class _AnyChecker(ast.NodeVisitor):
    def __init__(self) -> None:
        self.violations: list[tuple[int, int, str]] = []

    def visit_Attribute(self, node: ast.Attribute) -> None:
        # typing.Any
        if isinstance(node.value, ast.Name) and node.value.id == "typing" and node.attr == "Any":
            self.violations.append((node.lineno, node.col_offset, "typing.Any"))
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        # bare Any (e.g., from "from typing import Any")
        if node.id == "Any":
            self.violations.append((node.lineno, node.col_offset, "Any"))
        self.generic_visit(node)


def check_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    c = _AnyChecker()
    c.visit(tree)
    return [f"{path}:{ln}:{col}: disallow Any usage ({what})" for (ln, col, what) in c.violations]


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: guard_no_any_usage.py <paths...>")
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
