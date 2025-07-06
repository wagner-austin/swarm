# ruff_no_direct_discord_response.py
"""
Custom Ruff plugin: Forbids direct use of interaction.response.send_message, interaction.response.defer, and interaction.followup.send.
Allows these only inside bot/utils/discord_interactions.py.

Usage:
    ruff check --extend-select X999

Add to pyproject.toml:
    [tool.ruff.lint.per-file-ignores]
    "bot/utils/discord_interactions.py" = ["X999"]
"""

import ast
from typing import Any

FORBIDDEN = {
    ("response", "send_message"),
    ("response", "defer"),
    ("followup", "send"),
}


class NoDirectDiscordResponse(ast.NodeVisitor):
    def __init__(self, filename: str) -> None:
        self.errors: list[tuple[int, int]] = []
        self.filename = filename

    def visit_Attribute(self, node: ast.Attribute) -> Any:
        # Check for interaction.response.send_message, etc.
        if isinstance(node.value, ast.Attribute):
            if (node.value.attr, node.attr) in FORBIDDEN:
                # Only allow in discord_interactions.py
                if not self.filename.replace("\\", "/").endswith("discord_interactions.py"):
                    self.errors.append((node.lineno, node.col_offset))
        self.generic_visit(node)


def check_file(filename: str) -> int:
    with open(filename, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=filename)
    checker = NoDirectDiscordResponse(filename)
    checker.visit(tree)
    for lineno, col in checker.errors:
        print(
            f"{filename}:{lineno}:{col}: X999 Direct Discord interaction response forbidden; use safe_send/safe_defer"
        )
    return len(checker.errors)


if __name__ == "__main__":
    import sys

    n = 0
    import os
    from pathlib import Path
    from typing import Iterable

    def iter_py_files(path: str) -> Iterable[str]:
        """Yield .py file paths under a directory or a single file path."""
        p = Path(path)
        if p.is_dir():
            for f in p.rglob("*.py"):
                yield str(f)
        else:
            yield path

    for arg in sys.argv[1:]:
        for fname in iter_py_files(arg):
            rel = fname.replace("\\", "/").lower()
            if rel.startswith("tests/") or "/tests/" in rel or rel.startswith("tests\\"):
                continue
            if rel.endswith("mocks.py") or "/_mocks/" in rel:
                continue
                n += check_file(fname)
    sys.exit(1 if n else 0)
