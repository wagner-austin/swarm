"""
Guard: ban direct process-launch calls in library code.

Disallows:
- subprocess.Popen / run / call / check_call / check_output
- os.system / os.popen

Allows asyncio.create_subprocess_* (used in backends).
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


FORBIDDEN = {
    ("subprocess", "Popen"),
    ("subprocess", "run"),
    ("subprocess", "call"),
    ("subprocess", "check_call"),
    ("subprocess", "check_output"),
    ("os", "system"),
    ("os", "popen"),
}


class _PcallChecker(ast.NodeVisitor):
    def __init__(self) -> None:
        self.violations: list[tuple[int, int, str]] = []

    def visit_Call(self, node: ast.Call) -> None:
        fn = node.func
        if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
            mod = fn.value.id
            name = fn.attr
            if (mod, name) in FORBIDDEN:
                self.violations.append((node.lineno, node.col_offset, f"{mod}.{name}"))
        self.generic_visit(node)


def check_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    c = _PcallChecker()
    c.visit(tree)
    return [
        f"{path}:{ln}:{col}: forbidden process call ({what})" for (ln, col, what) in c.violations
    ]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: guard_no_pcalls.py <path>")
        return 2
    base = Path(argv[1])
    errors: list[str] = []
    for file in iter_py_files(base):
        errors.extend(check_file(file))
    if errors:
        for e in errors:
            print(e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
