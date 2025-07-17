"""
Script to flag dynamic dispatch patterns (getattr(...)(*args, **kwargs)) without filter_kwargs_for_method.
Run as a linter step to help enforce architectural guidelines.
"""

import ast
import sys
from pathlib import Path


class DispatchFilterLinter(ast.NodeVisitor):
    violations: list[tuple[int, int]]

    def __init__(self) -> None:
        self.violations = []

    def visit_Call(self, node: ast.Call) -> None:
        # Look for getattr(...)(*args, **kwargs)
        if (
            isinstance(node.func, ast.Call)
            and isinstance(node.func.func, ast.Name)
            and node.func.func.id == "getattr"
        ):
            # Check if **kwargs is present in the call
            for arg in node.keywords:
                if arg.arg is None:  # **kwargs
                    # Try to check if filter_kwargs_for_method is used (static heuristic)
                    if not (
                        isinstance(arg.value, ast.Call)
                        and getattr(arg.value.func, "id", None) == "filter_kwargs_for_method"
                    ):
                        self.violations.append((node.lineno, node.col_offset))
        self.generic_visit(node)


def lint_file(path: Path) -> int:
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=str(path))
    linter = DispatchFilterLinter()
    linter.visit(tree)
    for lineno, col in linter.violations:
        print(
            f"{path}:{lineno}:{col}: Dynamic dispatch with **kwargs missing filter_kwargs_for_method"
        )
    return len(linter.violations)


def main() -> None:
    root = Path(__file__).parent.parent / "swarm"
    total = 0
    for pyfile in root.rglob("*.py"):
        total += lint_file(pyfile)
    if total:
        print(
            f"\n{total} violation(s) found. Please use filter_kwargs_for_method for all dynamic dispatch with **kwargs."
        )
        sys.exit(1)
    else:
        print("No violations found.")


if __name__ == "__main__":
    main()
