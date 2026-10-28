"""Lists imported names a Python module never uses (a tiny stand-in for pyflakes).

    python dev/unused_imports.py app tests dev
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path


def unused(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported[(alias.asname or alias.name).split(".")[0]] = node.lineno
        elif isinstance(node, ast.ImportFrom) and node.module != "__future__":
            for alias in node.names:
                imported[alias.asname or alias.name] = node.lineno
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    used |= {n.value.id for n in ast.walk(tree) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)}
    exported = set()
    for node in ast.walk(tree):  # names listed in __all__ count as used
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "__all__" for t in node.targets):
            exported = {e.value for e in getattr(node.value, "elts", []) if isinstance(e, ast.Constant)}
    source_lines = path.read_text(encoding="utf-8").splitlines()
    return [
        f"{path}:{line}: unused import {name}"
        for name, line in sorted(imported.items(), key=lambda kv: kv[1])
        if name not in used and name not in exported and "noqa" not in source_lines[line - 1]
    ]


def main() -> int:
    problems: list[str] = []
    for root in sys.argv[1:] or ["app"]:
        for path in Path(root).rglob("*.py"):
            if "venv" in path.parts or "__pycache__" in path.parts:
                continue
            problems += unused(path)
    print("\n".join(problems) or "no unused imports")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
