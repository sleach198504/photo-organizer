from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path

from .fsutil import unique_destination
from .trips import get_trip_folder_for_photo

log = logging.getLogger(__name__)


def _dest_folder_for_photo(conn, row, dest_root: Path) -> Path:
    trip_folder = get_trip_folder_for_photo(conn, row["id"])
    if trip_folder:
        return dest_root / trip_folder

    dt = None
    if row["taken_at"]:
        try:
            dt = datetime.fromisoformat(row["taken_at"])
        except ValueError:
            dt = None
    if dt is None:
        # No usable EXIF date-taken - fall back to the file's modified date rather
        # than leaving it unsorted.
        dt = datetime.fromtimestamp(row["mtime"])
    return dest_root / f"{dt.year:04d}" / f"{dt.month:02d}"


def _photo_folder_label(path: Path, source_dir: Path) -> str:
    """The folder a photo is sitting in right now, relative to source_dir - the
    same label shown on the Organize page's folder list and used to key
    per-folder include/exclude decisions, so the two always agree on what a
    given folder is called."""
    parent = path.parent
    try:
        rel_parent = parent.resolve().relative_to(source_dir.resolve())
    except ValueError:
        # Photo was indexed under a source_dir this install no longer points
        # at - fall back to the immediate parent folder name rather than
        # failing outright.
        rel_parent = parent
    return str(rel_parent) if str(rel_parent) != "." else "(top-level folder)"


def get_folder_preview(conn, source_dir: Path) -> list[dict]:
    """Groups every currently-active photo by the folder it's sitting in right
    now (relative to source_dir), so the Organize page can show the user
    exactly which existing folder names are about to be replaced by Year/Month
    (or trip) folders, before they commit to running it."""
    rows = conn.execute("SELECT path FROM photos WHERE status = 'active'").fetchall()

    counts: dict[str, int] = {}
    for row in rows:
        label = _photo_folder_label(Path(row["path"]), source_dir)
        counts[label] = counts.get(label, 0) + 1

    return [
        {"folder": folder, "count": count}
        for folder, count in sorted(counts.items(), key=lambda kv: -kv[1])
    ]


def run_organize(
    conn,
    dest_root: Path,
    source_dir: Path,
    excluded_folders: set[str] | None = None,
    exclude_mode: str = "skip",
) -> dict:
    """Move every currently-active photo (survived review) into dest_root/year/month,
    based on when it was taken (falling back to file-modified-date if unknown).
    Safe to re-run - only 'active' photos are considered, so already-organized ones
    (status='organized') are skipped automatically.

    excluded_folders is a set of folder labels (as produced by get_folder_preview -
    e.g. "Trips/2024" or "(top-level folder)") the user opted out of this run, via
    the folder tree on the Organize page. A photo whose current folder label is in
    that set is handled per exclude_mode instead of the normal Year/Month/trip
    sorting:
      - "skip": left exactly where it is, completely untouched (still 'active',
        so it's picked up normally by a future Organize run that doesn't exclude
        it).
      - "move_as_is": moved into dest_root under its own current folder name,
        preserving that folder's structure, instead of being sorted into
        Year/Month - so it still ends up alongside everything else that got
        organized, just without its existing organization being dissolved.
    """
    excluded_folders = excluded_folders or set()
    rows = conn.execute("SELECT * FROM photos WHERE status = 'active'").fetchall()

    stats = {"moved": 0, "skipped": 0, "errors": 0}
    for row in rows:
        src = Path(row["path"])
        if not src.exists():
            log.warning("Photo %s no longer exists on disk at %s", row["id"], src)
            stats["errors"] += 1
            continue

        label = _photo_folder_label(src, source_dir)
        if label in excluded_folders:
            if exclude_mode == "skip":
                stats["skipped"] += 1
                continue
            dest_folder = dest_root / label
        else:
            dest_folder = _dest_folder_for_photo(conn, row, dest_root)

        dest = unique_destination(dest_folder / src.name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(src), str(dest))
        except OSError as exc:
            log.warning("Failed to move %s: %s", src, exc)
            stats["errors"] += 1
            continue

        new_live_pair = None
        if row["live_pair_path"]:
            live_src = Path(row["live_pair_path"])
            if live_src.exists():
                live_dest = unique_destination(dest.with_suffix(live_src.suffix))
                shutil.move(str(live_src), str(live_dest))
                new_live_pair = str(live_dest)

        conn.execute(
            "UPDATE photos SET status = 'organized', path = ?, live_pair_path = ? WHERE id = ?",
            (str(dest), new_live_pair, row["id"]),
        )
        stats["moved"] += 1
        if stats["moved"] % 200 == 0:
            conn.commit()
            log.info("Organized %d photos so far...", stats["moved"])

    conn.commit()
    return stats
