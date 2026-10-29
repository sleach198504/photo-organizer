"""Filing the photos that survived review into dated folders.

`plan_organize` decides where every photo would go *without touching anything* - the
UI shows that as a preview, and `run_organize` simply carries out the same plan, so
what you preview is exactly what happens.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .db import get_meta, log_activity, set_meta
from .fsutil import move_file, move_sidecars, unique_destination
from .progress import NULL_PROGRESS, Progress

log = logging.getLogger(__name__)

TOP_LEVEL_LABEL = "(top-level folder)"

# How dated folders are laid out. `example` is what the UI shows next to each option.
TEMPLATES = {
    "year_month": {"label": "Year, then month", "example": "2025 / 03"},
    "year_month_name": {"label": "Year, then month with its name", "example": "2025 / 03 March"},
    "year_month_day": {"label": "Year, month, then day", "example": "2025 / 03 / 14"},
    "year": {"label": "Year only", "example": "2025"},
}
DEFAULT_TEMPLATE = "year_month"

_INVALID_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def clean_folder_name(name: str) -> str:
    """Make a user- or place-derived name safe to use as one Windows folder name."""
    cleaned = _INVALID_NAME_CHARS.sub("-", name).strip().rstrip(".")
    return cleaned or "Untitled"


def dated_subfolder(dt: datetime, template: str) -> Path:
    if template == "year":
        return Path(f"{dt.year:04d}")
    if template == "year_month_name":
        return Path(f"{dt.year:04d}") / f"{dt.month:02d} {dt.strftime('%B')}"
    if template == "year_month_day":
        return Path(f"{dt.year:04d}") / f"{dt.month:02d}" / f"{dt.day:02d}"
    return Path(f"{dt.year:04d}") / f"{dt.month:02d}"


def _photo_datetime(row) -> datetime:
    if row["taken_at"]:
        try:
            return datetime.fromisoformat(row["taken_at"])
        except ValueError:
            pass
    # No usable capture date - fall back to the file's modified date rather than
    # leaving it unsorted.
    return datetime.fromtimestamp(row["mtime"])


def _trip_folder_map(conn) -> dict[int, Path]:
    rows = conn.execute(
        """
        SELECT tcm.photo_id AS photo_id, tc.kind AS kind, COALESCE(tc.custom_name, tc.suggested_name) AS name
        FROM trip_candidate_members tcm JOIN trip_candidates tc ON tc.id = tcm.trip_id
        WHERE tc.status = 'pending'
        """
    ).fetchall()
    return {
        r["photo_id"]: Path("Trips" if r["kind"] == "vacation" else "Day Trips") / clean_folder_name(r["name"])
        for r in rows
    }


def photo_folder_label(path: Path, source_dir: Path) -> str:
    """The folder a photo is sitting in right now, relative to source_dir - the label
    shown in the Organize folder tree and used to key include/exclude choices."""
    parent = path.parent
    try:
        rel_parent = parent.resolve().relative_to(source_dir.resolve())
    except ValueError:
        # Photo was indexed under a source_dir this install no longer points at -
        # fall back to the parent folder name rather than failing outright.
        rel_parent = parent
    return rel_parent.as_posix() if str(rel_parent) != "." else TOP_LEVEL_LABEL


def get_folder_preview(conn, source_dir: Path) -> list[dict]:
    """Every folder that currently holds active photos, with counts - the tree the
    person can uncheck folders in."""
    rows = conn.execute("SELECT path FROM photos WHERE status = 'active'").fetchall()
    counts: dict[str, int] = {}
    for row in rows:
        label = photo_folder_label(Path(row["path"]), source_dir)
        counts[label] = counts.get(label, 0) + 1
    return [{"folder": f, "count": c} for f, c in sorted(counts.items(), key=lambda kv: kv[0].lower())]


@dataclass
class PlannedMove:
    photo_id: int
    src: Path
    dest_folder: Path | None  # relative to the destination root; None = leave in place
    action: str               # organize | as_is | skip | missing


def plan_organize(
    conn,
    source_dir: Path,
    excluded_folders: set[str] | None = None,
    exclude_mode: str = "skip",
    template: str = DEFAULT_TEMPLATE,
) -> list[PlannedMove]:
    """Where every active photo would go. Pure decision-making: touches nothing."""
    excluded_folders = excluded_folders or set()
    if template not in TEMPLATES:
        template = DEFAULT_TEMPLATE
    trips = _trip_folder_map(conn)

    plan: list[PlannedMove] = []
    for row in conn.execute(
        "SELECT id, path, taken_at, mtime FROM photos WHERE status = 'active' ORDER BY id"
    ):
        src = Path(row["path"])
        if not src.exists():
            plan.append(PlannedMove(row["id"], src, None, "missing"))
            continue
        label = photo_folder_label(src, source_dir)
        if label in excluded_folders:
            if exclude_mode == "skip":
                plan.append(PlannedMove(row["id"], src, None, "skip"))
            else:
                folder = Path(*[clean_folder_name(p) for p in label.split("/")]) if label != TOP_LEVEL_LABEL else Path("Loose photos")
                plan.append(PlannedMove(row["id"], src, folder, "as_is"))
            continue
        folder = trips.get(row["id"]) or dated_subfolder(_photo_datetime(row), template)
        plan.append(PlannedMove(row["id"], src, folder, "organize"))
    return plan


def preview_organize(
    conn,
    source_dir: Path,
    excluded_folders: set[str] | None = None,
    exclude_mode: str = "skip",
    template: str = DEFAULT_TEMPLATE,
) -> dict:
    plan = plan_organize(conn, source_dir, excluded_folders, exclude_mode, template)
    folders: dict[str, dict] = {}
    totals = {"organize": 0, "as_is": 0, "skip": 0, "missing": 0}
    for move in plan:
        totals[move.action] += 1
        if move.dest_folder is None:
            continue
        key = move.dest_folder.as_posix()
        entry = folders.setdefault(key, {"path": key, "count": 0, "as_is": move.action == "as_is"})
        entry["count"] += 1
    return {
        "folders": sorted(folders.values(), key=lambda f: f["path"].lower()),
        "totals": totals,
        "moving": totals["organize"] + totals["as_is"],
    }


def run_organize(
    conn,
    dest_root: Path,
    source_dir: Path,
    excluded_folders: set[str] | None = None,
    exclude_mode: str = "skip",
    template: str = DEFAULT_TEMPLATE,
    progress: Progress = NULL_PROGRESS,
) -> dict:
    """Move every active photo to the place `plan_organize` chose for it.
    Safe to re-run - only 'active' photos are considered, and moved ones become
    'organized'. Each moved photo remembers where it came from, so the most recent
    run can be undone with `undo_organize`."""
    plan = plan_organize(conn, source_dir, excluded_folders, exclude_mode, template)
    stats = {"moved": 0, "skipped": 0, "errors": 0}
    progress.start(sum(1 for m in plan if m.action in ("organize", "as_is")))

    batch = datetime.now(timezone.utc).isoformat()
    set_meta(conn, "last_organize_batch", batch)
    set_meta(conn, "last_organize_root", str(dest_root))
    set_meta(conn, "last_organize_root_existed", "1" if dest_root.exists() else "0")
    conn.commit()

    try:
        for move in plan:
            if move.action == "skip":
                stats["skipped"] += 1
                continue
            if move.action == "missing":
                log.warning("Photo %s no longer exists on disk at %s", move.photo_id, move.src)
                stats["errors"] += 1
                continue

            progress.check()
            row = conn.execute("SELECT live_pair_path FROM photos WHERE id = ?", (move.photo_id,)).fetchone()
            dest = unique_destination(dest_root / move.dest_folder / move.src.name)
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                move_file(move.src, dest)
            except OSError as exc:
                log.warning("Failed to move %s: %s", move.src, exc)
                stats["errors"] += 1
                progress.advance(1, move.src.name)
                continue

            new_live_pair = None
            if row and row["live_pair_path"]:
                live_src = Path(row["live_pair_path"])
                if live_src.exists():
                    live_dest = unique_destination(dest.with_suffix(live_src.suffix))
                    try:
                        move_file(live_src, live_dest)
                        new_live_pair = str(live_dest)
                    except OSError as exc:
                        log.warning("Failed to move the Live Photo clip %s: %s", live_src, exc)
            move_sidecars(move.src, dest)

            conn.execute(
                "UPDATE photos SET status = 'organized', path = ?, live_pair_path = ?, "
                "organized_from = ?, organize_batch = ? WHERE id = ?",
                (str(dest), new_live_pair, str(move.src), batch, move.photo_id),
            )
            stats["moved"] += 1
            progress.advance(1, move.src.name)
            if stats["moved"] % 200 == 0:
                conn.commit()
    finally:
        # Also when stopped part-way: the files that did move must stay recorded, or they
        # would be lost to the library (and impossible to undo).
        if stats["moved"]:
            conn.execute(
                "UPDATE photos SET organized_from = NULL, organize_batch = NULL "
                "WHERE organize_batch IS NOT NULL AND organize_batch != ?", (batch,))
        conn.commit()

    if stats["moved"]:
        log_activity(conn, "organized", f"Filed {stats['moved']:,} items into dated folders", str(dest_root))
        conn.commit()
    return stats


def undo_info(conn) -> dict | None:
    """What the most recent Organize did and can still be undone, or None."""
    batch = get_meta(conn, "last_organize_batch")
    if not batch:
        return None
    count = conn.execute(
        "SELECT COUNT(*) c FROM photos WHERE status = 'organized' AND organize_batch = ? AND organized_from IS NOT NULL",
        (batch,),
    ).fetchone()["c"]
    if not count:
        return None
    return {"count": count, "when": batch, "dest_root": get_meta(conn, "last_organize_root")}


def _remove_empty_folders(folders: set[Path], dest_root: Path, remove_root: bool) -> None:
    """Tidy up the dated folders Organize created. Only empty folders go (rmdir refuses
    anything else), and never anything outside the destination."""
    for folder in sorted(folders, key=lambda f: len(f.parts), reverse=True):
        current = folder
        while current != dest_root and current.is_relative_to(dest_root):
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent
    if remove_root:
        try:
            dest_root.rmdir()
        except OSError:
            pass


def undo_organize(conn, progress: Progress = NULL_PROGRESS) -> dict:
    """Put the photos from the most recent Organize back where they came from.
    A photo that was moved or deleted since is left alone and counted as missing; if
    something new now sits in its old place the photo comes back under a numbered name."""
    batch = get_meta(conn, "last_organize_batch")
    stats = {"restored": 0, "missing": 0, "renamed": 0, "failed": 0}
    if not batch:
        return stats
    rows = conn.execute(
        "SELECT id, path, live_pair_path, organized_from FROM photos "
        "WHERE status = 'organized' AND organize_batch = ? AND organized_from IS NOT NULL ORDER BY id",
        (batch,),
    ).fetchall()
    dest_root = Path(get_meta(conn, "last_organize_root") or "")
    root_created_here = get_meta(conn, "last_organize_root_existed") == "0"
    progress.start(len(rows))
    emptied: set[Path] = set()

    try:
        for row in rows:
            progress.check()
            current, original = Path(row["path"]), Path(row["organized_from"])
            if not current.exists():
                log.warning("Cannot put back %s: it is no longer at %s", original.name, current)
                stats["missing"] += 1
                progress.advance(1, original.name)
                continue

            target = unique_destination(original)
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                move_file(current, target)
            except OSError as exc:
                log.warning("Failed to put %s back: %s", original, exc)
                stats["failed"] += 1
                progress.advance(1, original.name)
                continue
            emptied.add(current.parent)

            restored_live = None
            if row["live_pair_path"]:
                live_current = Path(row["live_pair_path"])
                if live_current.exists():
                    live_target = unique_destination(target.with_suffix(live_current.suffix))
                    try:
                        move_file(live_current, live_target)
                        restored_live = str(live_target)
                        emptied.add(live_current.parent)
                    except OSError as exc:
                        log.warning("Failed to put the Live Photo clip %s back: %s", live_current, exc)
            move_sidecars(current, target)

            conn.execute(
                "UPDATE photos SET status = 'active', path = ?, live_pair_path = ?, "
                "organized_from = NULL, organize_batch = NULL WHERE id = ?",
                (str(target), restored_live, row["id"]),
            )
            stats["restored"] += 1
            stats["renamed"] += target != original
            progress.advance(1, original.name)
            if stats["restored"] % 200 == 0:
                conn.commit()
    finally:
        conn.commit()

    if dest_root.parts:
        _remove_empty_folders(emptied, dest_root, remove_root=root_created_here)
    if stats["restored"]:
        log_activity(conn, "organized", f"Put {stats['restored']:,} items back where they were", str(dest_root))
        conn.commit()
    return stats
