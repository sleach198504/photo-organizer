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


def move_sidecars(old_photo: Path, new_photo: Path) -> list[Path]:
    """Carry an iPhone edit-instructions file (IMG_1234.AAE) along with its photo.

    Call it after the photo (and any Live Photo clip) has moved from `old_photo` to
    `new_photo`. The file only moves when no other photo or video of the same name is still
    in the old folder, so it never leaves behind something else's edit data. Returns where
    it ended up; a failure is logged and never stops the photo's own move."""
    from .indexer import IMAGE_EXTS, VIDEO_EXTS
    from .iphone import SIDECAR_EXTENSIONS

    moved: list[Path] = []
    for ext in SIDECAR_EXTENSIONS:
        sidecar = old_photo.with_suffix(ext)
        if not sidecar.is_file() or sidecar.resolve() == old_photo.resolve():
            continue
        if any(old_photo.with_suffix(other).exists() for other in (*IMAGE_EXTS, *VIDEO_EXTS)):
            continue  # another file with this name is still here and may own it
        target = unique_destination(new_photo.with_suffix(sidecar.suffix))
        try:
            move_file(sidecar, target)
            moved.append(target)
        except OSError:
            continue
    return moved


def delete_sidecars(photo: Path, boundary: Path) -> int:
    """Delete the edit-instructions file left beside a photo that has just been deleted,
    but only inside `boundary` and only if nothing else with the same name remains."""
    from .indexer import IMAGE_EXTS, VIDEO_EXTS
    from .iphone import SIDECAR_EXTENSIONS

    removed = 0
    for ext in SIDECAR_EXTENSIONS:
        sidecar = photo.with_suffix(ext)
        if not sidecar.is_file() or not sidecar.resolve().is_relative_to(boundary.resolve()):
            continue
        if any(photo.with_suffix(other).exists() for other in (*IMAGE_EXTS, *VIDEO_EXTS)):
            continue
        try:
            sidecar.unlink()
            removed += 1
        except OSError:
            continue
    return removed
