# ruff_no_direct_discord_response.py
"""
Guard: Forbid direct use of Discord interaction response send/defer.

Forbids calls like interaction.response.send_message, interaction.response.defer,
and interaction.followup.send outside the dedicated adapter module.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Iterable

FORBIDDEN = {
    ("response", "send_message"),
    ("response", "defer"),
    ("followup", "send"),
}


class NoDirectDiscordResponse(ast.NodeVisitor):
    def __init__(self, filename: str) -> None:
        self.errors: list[tuple[int, int]] = []
        self.filename = filename

    def visit_Attribute(self, node: ast.Attribute) -> None:
        # Check for interaction.response.send_message, etc.
        if isinstance(node.value, ast.Attribute):
            if (node.value.attr, node.attr) in FORBIDDEN:
                # Only allow in discord_interactions.py adapter
                if not self.filename.replace("\\", "/").endswith("discord_interactions.py"):
                    self.errors.append((node.lineno, node.col_offset))
        self.generic_visit(node)


def check_file(filename: str) -> int:
    text = Path(filename).read_text(encoding="utf-8")
    tree = ast.parse(text, filename=filename)
    checker = NoDirectDiscordResponse(filename)
    checker.visit(tree)
    for lineno, col in checker.errors:
        print(
            f"{filename}:{lineno}:{col}: X999 Direct Discord response forbidden; use adapter helpers"
        )
    return len(checker.errors)


def iter_py_files(path: str) -> Iterable[str]:
    p = Path(path)
    if p.is_dir():
        for f in p.rglob("*.py"):
            yield str(f)
    else:
        yield path


if __name__ == "__main__":
    n = 0
    for arg in sys.argv[1:]:
        for fname in iter_py_files(arg):
            rel = fname.replace("\\", "/").lower()
            if rel.startswith("tests/") or "/tests/" in rel or rel.startswith("tests\\"):
                continue
            if rel.endswith("mocks.py") or "/_mocks/" in rel:
                continue
            n += check_file(fname)
    sys.exit(1 if n else 0)
