from __future__ import annotations

import shutil
import time
from pathlib import Path

# On Windows a file another program is reading (a thumbnail being drawn, antivirus, a
# sync client) cannot be moved for a moment. Waiting briefly turns that into a success.
MOVE_RETRIES = 8
MOVE_FIRST_WAIT = 0.1


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


def move_file(src: str | Path, dest: str | Path) -> None:
    """shutil.move that waits out short-lived locks instead of failing the photo."""
    wait = MOVE_FIRST_WAIT
    for attempt in range(MOVE_RETRIES):
        try:
            shutil.move(str(src), str(dest))
            return
        except PermissionError:
            if attempt == MOVE_RETRIES - 1:
                raise
            time.sleep(wait)
            wait = min(wait * 2, 1.0)
