"""
Guard: Disallow awaiting personas.visible (or its aliases) inside autocomplete handlers.

Rationale:
- Discord autocomplete must respond in ~3 seconds and cannot be deferred.
- Awaiting persona visibility (which may perform network I/O) in autocomplete
  can exceed the SLA and cause 10062 Unknown interaction errors.

Usage: python scripts/guard_no_await_persona_visible_in_autocomplete.py <paths...>
Exits non‑zero and prints offending locations when violations are found.
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


class _AutocompleteAwaitChecker(ast.NodeVisitor):
    """AST checker for unsafe constructs within autocomplete functions.

    Disallows:
    - Any ``await`` expression (autocomplete must be fast and non-blocking).
    - Awaiting ``personas.visible`` (or aliases).
    - Awaiting common network libs (httpx, aiohttp, requests, openai, google.genai).
    - Calling ``interaction.response.*`` or ``interaction.followup.*`` inside autocomplete (library sends response).
    """

    def __init__(self) -> None:
        # Local names bound to the personas module (e.g., "p" from "from swarm.ai import personas as p")
        self._personas_mod_aliases: set[str] = set()
        # Local names bound to the personas.visible function (e.g., "visible" or "persona_visible")
        self._visible_local_names: set[str] = set()
        # Collected violations: (lineno, col, message)
        self.violations: list[tuple[int, int, str]] = []

    # ------------------------ import resolution ------------------------
    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802 (ast API)
        mod = node.module or ""
        if mod == "swarm.ai.personas":
            for alias in node.names:
                if alias.name == "visible":
                    self._visible_local_names.add(alias.asname or alias.name)
        elif mod == "swarm.ai":
            for alias in node.names:
                if alias.name == "personas":
                    self._personas_mod_aliases.add(alias.asname or alias.name)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802 (ast API)
        # Only handle explicit alias to bind module name locally.
        for alias in node.names:
            if alias.name == "swarm.ai.personas" and alias.asname:
                self._personas_mod_aliases.add(alias.asname)
        self.generic_visit(node)

    # ------------------------ function scanning ------------------------
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        if self._is_autocomplete(node):
            self._scan_autocomplete_body(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        if self._is_autocomplete(node):
            self._scan_autocomplete_body(node)
        self.generic_visit(node)

    # ------------------------ helpers ------------------------
    @staticmethod
    def _decorator_is_autocomplete(deco: ast.expr) -> bool:
        # Matches @something.autocomplete(...)
        if isinstance(deco, ast.Call):
            fn = deco.func
            if isinstance(fn, ast.Attribute) and fn.attr == "autocomplete":
                return True
            if isinstance(fn, ast.Name) and fn.id == "autocomplete":
                return True
        return False

    def _is_autocomplete(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        name = node.name.lower()
        if "autocomplete" in name:
            return True
        for deco in node.decorator_list:
            if self._decorator_is_autocomplete(deco):
                return True
        return False

    @staticmethod
    def _base_name(expr: ast.expr) -> str | None:
        # Unwind attribute chains to a bare Name id, if possible.
        cur: ast.expr = expr
        while isinstance(cur, ast.Attribute):
            cur = cur.value
        return cur.id if isinstance(cur, ast.Name) else None

    def _is_personas_visible_call(self, call: ast.Call) -> bool:
        fn = call.func
        # Case 1: direct name (from import visible as X)
        if isinstance(fn, ast.Name) and fn.id in (self._visible_local_names | {"persona_visible"}):
            return True
        # Case 2: module alias .visible
        if isinstance(fn, ast.Attribute) and fn.attr == "visible":
            base = self._base_name(fn.value)
            if base in self._personas_mod_aliases:
                return True
        return False

    @staticmethod
    def _dotted_path(expr: ast.expr) -> list[str]:
        parts: list[str] = []
        cur: ast.expr = expr
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        parts.reverse()
        return parts

    def _is_network_call(self, call: ast.Call) -> bool:
        # Heuristic: base module name in common network SDKs
        fn = call.func
        roots = {"httpx", "aiohttp", "requests", "openai", "google"}
        path = self._dotted_path(fn)
        if not path:
            return False
        if path[0] in roots:
            # openai.* , httpx.* , aiohttp.* , requests.* , google.* (e.g., google.genai)
            return True
        # Also flag swarm.ai.providers.* calls
        if len(path) >= 3 and path[0] == "swarm" and path[1] == "ai" and path[2] == "providers":
            return True
        # Common fetchers on bot/self.bot: fetch_*, application_info
        if path[-1].startswith("fetch") or path[-1] == "application_info":
            # e.g., self.bot.fetch_user(), bot.application_info()
            if "bot" in path:
                return True
        return False

    def _is_interaction_response_call(self, call: ast.Call) -> bool:
        # Detect calls on interaction.response.* or interaction.followup.*
        path = self._dotted_path(call.func)
        if (
            len(path) >= 3
            and path[0] in {"interaction", "ctx", "inter"}
            and path[1] in {"response", "followup"}
        ):
            return True
        return False

    def _scan_autocomplete_body(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for sub in ast.walk(node):
            # Blanket ban on awaits inside autocomplete
            if isinstance(sub, ast.Await):
                self.violations.append(
                    (sub.lineno, sub.col_offset, "await used inside autocomplete")
                )
                if isinstance(sub.value, ast.Call):
                    if self._is_personas_visible_call(sub.value):
                        msg = "await personas.visible (or alias) inside autocomplete"
                        self.violations.append((sub.lineno, sub.col_offset, msg))
                    if self._is_network_call(sub.value):
                        msg = "await network/SDK call inside autocomplete"
                        self.violations.append((sub.lineno, sub.col_offset, msg))
                    if self._is_interaction_response_call(sub.value):
                        msg = "await interaction.response/followup call inside autocomplete"
                        self.violations.append((sub.lineno, sub.col_offset, msg))

            # Also disallow calling interaction.response.* or interaction.followup.* even without await
            if isinstance(sub, ast.Call) and self._is_interaction_response_call(sub):
                self.violations.append(
                    (
                        sub.lineno,
                        sub.col_offset,
                        "interaction.response/followup call inside autocomplete",
                    )
                )


def check_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    c = _AutocompleteAwaitChecker()
    c.visit(tree)
    return [
        f"{path}:{ln}:{col}: disallow persona visibility await in autocomplete ({what})"
        for (ln, col, what) in c.violations
    ]


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: guard_no_await_persona_visible_in_autocomplete.py <paths...>")
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
