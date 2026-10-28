from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .config import Config
from .fsutil import unique_destination
from .progress import NULL_PROGRESS, Progress

log = logging.getLogger(__name__)


def _relative_dest(src: Path, source_dir: Path, quarantine_dir: Path) -> Path:
    try:
        rel = src.resolve().relative_to(source_dir.resolve())
    except ValueError:
        # Photo was indexed under a source_dir this install no longer points at -
        # fall back to just the filename rather than failing the whole move.
        rel = Path(src.name)
    return quarantine_dir / rel


def _is_within(path: Path, folder: Path) -> bool:
    try:
        path.resolve().relative_to(folder.resolve())
        return True
    except (ValueError, OSError):
        return False


def _resolve_pending_recommendations(conn, photo_id: int, decision: str) -> None:
    """Whenever a photo actually gets moved, close out any recommendations still
    sitting 'pending' for it - otherwise a photo quarantined via a path that
    doesn't go through decide() leaves a stale card pointing at an already-moved
    photo on the review page."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE recommendations SET decision = ?, decided_at = ? WHERE photo_id = ? AND decision = 'pending'",
        (decision, now, photo_id),
    )


def quarantine_photo(conn, config: Config, photo_id: int) -> bool:
    """Move a photo (and its Live Photo video pair, if any) into the review/quarantine
    folder, remembering where it came from so it can be restored. Safe to call more
    than once for the same photo - a no-op if it's already been moved. Returns True
    if the photo is now (or already was) out of the library."""
    row = conn.execute("SELECT * FROM photos WHERE id = ?", (photo_id,)).fetchone()
    if row is None or row["status"] != "active":
        return False

    now = datetime.now(timezone.utc).isoformat()
    src = Path(row["path"])
    if not src.exists():
        log.warning("Photo %s no longer exists on disk at %s - marking quarantined anyway", photo_id, src)
        conn.execute(
            "UPDATE photos SET status = 'quarantined', original_path = ?, quarantined_at = ? WHERE id = ?",
            (str(src), now, photo_id),
        )
        _resolve_pending_recommendations(conn, photo_id, "approved")
        return True

    dest = unique_destination(_relative_dest(src, config.source_dir, config.quarantine_dir))
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))

    new_live_pair = None
    if row["live_pair_path"]:
        live_src = Path(row["live_pair_path"])
        if live_src.exists():
            live_dest = unique_destination(dest.with_suffix(live_src.suffix))
            try:
                shutil.move(str(live_src), str(live_dest))
                new_live_pair = str(live_dest)
            except OSError as exc:
                log.warning("Could not move the Live Photo clip %s: %s", live_src, exc)

    conn.execute(
        "UPDATE photos SET status = 'quarantined', path = ?, live_pair_path = ?, "
        "original_path = ?, quarantined_at = ? WHERE id = ?",
        (str(dest), new_live_pair, str(src), now, photo_id),
    )
    _resolve_pending_recommendations(conn, photo_id, "approved")
    return True


def _original_location(row, config: Config) -> Path:
    if row["original_path"]:
        return Path(row["original_path"])
    # Removed before original paths were recorded: the review folder mirrors the
    # source folder's structure, so invert that mapping.
    try:
        rel = Path(row["path"]).resolve().relative_to(config.quarantine_dir.resolve())
        return config.source_dir / rel
    except ValueError:
        return config.source_dir / Path(row["path"]).name


def restore_photo(conn, config: Config, photo_id: int) -> bool:
    """Put a removed photo (and its Live Photo clip) back where it came from."""
    row = conn.execute("SELECT * FROM photos WHERE id = ?", (photo_id,)).fetchone()
    if row is None or row["status"] != "quarantined":
        return False

    current = Path(row["path"])
    if not current.exists():
        log.warning("Cannot restore photo %s - %s is gone from the review folder", photo_id, current)
        return False

    dest = unique_destination(_original_location(row, config))
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(current), str(dest))

    new_live_pair = None
    if row["live_pair_path"]:
        live_current = Path(row["live_pair_path"])
        if live_current.exists():
            live_dest = unique_destination(dest.with_suffix(live_current.suffix))
            try:
                shutil.move(str(live_current), str(live_dest))
                new_live_pair = str(live_dest)
            except OSError as exc:
                log.warning("Could not restore the Live Photo clip %s: %s", live_current, exc)

    conn.execute(
        "UPDATE photos SET status = 'active', path = ?, live_pair_path = ?, "
        "original_path = NULL, quarantined_at = NULL WHERE id = ?",
        (str(dest), new_live_pair, photo_id),
    )
    # Restoring is a decision to keep it: don't re-flag it for the same reasons.
    conn.execute(
        "UPDATE recommendations SET decision = 'rejected' WHERE photo_id = ? AND decision = 'approved'",
        (photo_id,),
    )
    _prune_empty_dirs(config.quarantine_dir)
    return True


def decide(conn, config: Config, photo_id: int, decision: str) -> None:
    if decision not in ("approved", "rejected"):
        raise ValueError(f"invalid decision: {decision}")

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE recommendations SET decision = ?, decided_at = ? WHERE photo_id = ? AND decision = 'pending'",
        (decision, now, photo_id),
    )
    if decision == "approved":
        quarantine_photo(conn, config, photo_id)
    conn.commit()


def quarantine_photos_batch(conn, config: Config, photo_ids: list[int]) -> dict:
    moved = 0
    for photo_id in photo_ids:
        if quarantine_photo(conn, config, photo_id):
            moved += 1
    conn.commit()
    return {"moved": moved}


def execute_approved_recommendations(conn, config: Config) -> int:
    """Move any photo that's already 'approved' but not yet moved - covers
    auto_quarantine_exact_duplicates, which marks recommendations approved at
    analysis time without moving the file itself."""
    rows = conn.execute(
        """
        SELECT DISTINCT r.photo_id
        FROM recommendations r
        JOIN photos p ON p.id = r.photo_id
        WHERE r.decision = 'approved' AND p.status = 'active'
        """
    ).fetchall()
    count = 0
    for row in rows:
        if quarantine_photo(conn, config, row["photo_id"]):
            count += 1
    conn.commit()
    return count


def get_quarantine_stats(conn) -> dict:
    """Reports what's actually sitting in the review folder right now, not just
    what the database last recorded - a row whose file was removed outside the
    app (by hand, antivirus, etc.) is dropped here rather than left to inflate
    the count or let a later purge silently no-op on a photo that isn't there."""
    rows = conn.execute(
        "SELECT id, path, live_pair_path, size_bytes FROM photos WHERE status = 'quarantined'"
    ).fetchall()
    total_bytes = 0
    count = 0
    for row in rows:
        if not Path(row["path"]).exists():
            conn.execute("DELETE FROM photos WHERE id = ?", (row["id"],))
            continue
        count += 1
        total_bytes += row["size_bytes"] or 0
        if row["live_pair_path"]:
            try:
                total_bytes += Path(row["live_pair_path"]).stat().st_size
            except OSError:
                pass
    conn.commit()
    return {"count": count, "total_bytes": total_bytes}


def _prune_empty_dirs(root: Path) -> None:
    if not root.exists():
        return
    for dirpath, _dirnames, _filenames in os.walk(root, topdown=False):
        d = Path(dirpath)
        if d == root:
            continue
        try:
            if not any(d.iterdir()):
                d.rmdir()
        except OSError:
            pass


def purge_photos(
    conn, config: Config, photo_ids: list[int] | None = None, progress: Progress = NULL_PROGRESS
) -> dict:
    """Permanently delete photos sitting in the review folder (all of them, or just
    photo_ids). Irreversible - the caller is responsible for confirming first.

    Defense in depth: only files that are actually inside the review folder are ever
    deleted, so a corrupted database row can never point this at someone's real
    photo library."""
    if photo_ids is None:
        rows = conn.execute(
            "SELECT id, path, live_pair_path FROM photos WHERE status = 'quarantined'"
        ).fetchall()
    else:
        placeholders = ",".join("?" * len(photo_ids)) or "NULL"
        rows = conn.execute(
            f"SELECT id, path, live_pair_path FROM photos WHERE status = 'quarantined' AND id IN ({placeholders})",
            photo_ids,
        ).fetchall()

    deleted = errors = 0
    freed_bytes = 0
    progress.start(len(rows))
    for row in rows:
        path = Path(row["path"])
        progress.advance(1, path.name)
        try:
            if path.exists():
                if not _is_within(path, config.quarantine_dir):
                    log.warning("Refusing to delete %s: it is not inside the review folder", path)
                    errors += 1
                    continue
                freed_bytes += path.stat().st_size
                path.unlink()
            if row["live_pair_path"]:
                live_path = Path(row["live_pair_path"])
                if live_path.exists() and _is_within(live_path, config.quarantine_dir):
                    freed_bytes += live_path.stat().st_size
                    live_path.unlink()
            conn.execute("DELETE FROM photos WHERE id = ?", (row["id"],))
            deleted += 1
        except OSError as exc:
            log.warning("Failed to delete %s: %s", path, exc)
            errors += 1
    conn.commit()

    _prune_empty_dirs(config.quarantine_dir)
    return {"deleted": deleted, "errors": errors, "freed_bytes": freed_bytes}


def purge_quarantined(conn, config: Config) -> dict:
    """Back-compat wrapper: delete everything in the review folder."""
    return purge_photos(conn, config, None)
