from __future__ import annotations

from pathlib import Path


def unique_destination(path: Path) -> Path:
    """If path already exists, append ' (2)', ' (3)', etc. until it doesn't."""
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    n = 1
    while True:
        candidate = path.with_name(f"{stem} ({n}){suffix}")
        if not candidate.exists():
            return candidate
        n += 1
